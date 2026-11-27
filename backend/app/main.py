"""FastAPI app: upload an invoice, stream its run live (SSE), browse history, act on held invoices."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sse_starlette.sse import EventSourceResponse

from app import settings
from app.db import LedgerInvoice, POLine, PurchaseOrder, Run, RunEvent, Session, Vendor, init_db, utcnow
from app.pdf import sha256_bytes
from app.pipeline import STAGES, run_pipeline

SAMPLES_DIR = settings.BACKEND_DIR.parent / "samples"
FRONTEND_DIST = settings.BACKEND_DIR.parent / "frontend" / "dist"
_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with Session() as s:  # runs cut off by a restart get a terminal state, never stuck at "running"
        await s.execute(update(Run).where(Run.status.in_(("queued", "running")))
                        .values(status="failed", error="Interrupted by server restart", finished_at=utcnow()))
        await s.commit()
    yield
    for t in _tasks:
        t.cancel()


app = FastAPI(title="Invoice AP Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ response models
class RunSummary(BaseModel):
    id: str
    filename: str
    status: str
    current_stage: str | None
    pdf_kind: str | None
    decision: str | None
    decision_summary: str | None
    vendor_name: str | None
    invoice_number: str | None
    total: float | None
    currency: str | None
    po_number: str | None
    reviewer_action: str | None
    reviewer_note: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class EventOut(BaseModel):
    id: int
    stage: str
    status: str
    title: str
    data: dict[str, Any] | None
    ts: datetime


class RunDetail(RunSummary):
    result: dict[str, Any] | None
    events: list[EventOut]
    stages: list[list[str]]


class Stats(BaseModel):
    total: int
    approved: int
    needs_review: int
    rejected: int
    running: int
    failed: int
    approved_amounts: dict[str, float]  # per currency: never add pounds to dollars
    held_amounts: dict[str, float]


class ReviewIn(BaseModel):
    action: Literal["approved", "rejected"]
    note: str = ""


def _summary(r: Run) -> RunSummary:
    return RunSummary.model_validate(r, from_attributes=True)


# ------------------------------------------------------------------ runs
async def _start(filename: str, data: bytes) -> RunSummary:
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Only PDF invoices are supported")
    digest = sha256_bytes(data)
    (settings.UPLOAD_DIR / f"{digest}.pdf").write_bytes(data)
    run = Run(id=uuid.uuid4().hex[:10], filename=filename, file_hash=digest, status="queued")
    async with Session() as s:
        s.add(run)
        await s.commit()
    task = asyncio.create_task(run_pipeline(run.id, data), name=run.id)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return _summary(run)


@app.post("/api/runs", response_model=RunSummary)
async def create_run(file: UploadFile) -> RunSummary:
    return await _start(file.filename or "invoice.pdf", await file.read())


@app.get("/api/runs", response_model=list[RunSummary])
async def list_runs(decision: str | None = None, q: str | None = None,
                    limit: int = Query(200, le=1000)) -> list[RunSummary]:
    stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if decision:
        stmt = stmt.where(Run.decision == decision)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Run.filename.ilike(like) | Run.vendor_name.ilike(like) | Run.invoice_number.ilike(like))
    async with Session() as s:
        return [_summary(r) for r in (await s.scalars(stmt)).all()]


@app.get("/api/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str) -> RunDetail:
    async with Session() as s:
        run = await s.get(Run, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        events = (await s.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id))).all()
    return RunDetail(**_summary(run).model_dump(), result=run.result,
                     events=[EventOut.model_validate(e, from_attributes=True) for e in events], stages=STAGES)


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str, after: int = 0):
    """Replays every event after `after`, then follows until the run is terminal. Refresh-safe."""

    async def gen():
        last = after
        while True:
            async with Session() as s:
                run = await s.get(Run, run_id)
                if not run:
                    yield {"event": "error", "data": json.dumps({"detail": "Run not found"})}
                    return
                evs = (await s.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > last)
                                       .order_by(RunEvent.id))).all()
            for e in evs:
                last = e.id
                yield {"event": "stage", "id": str(e.id),
                       "data": EventOut.model_validate(e, from_attributes=True).model_dump_json()}
            if run.status in ("completed", "failed") and not evs:
                yield {"event": "done", "data": json.dumps({"status": run.status, "decision": run.decision})}
                return
            await asyncio.sleep(settings.SSE_POLL_INTERVAL_SECONDS)

    return EventSourceResponse(gen())


@app.get("/api/runs/{run_id}/pdf")
async def run_pdf(run_id: str):
    async with Session() as s:
        run = await s.get(Run, run_id)
    if not run:
        raise HTTPException(404)
    return FileResponse(settings.UPLOAD_DIR / f"{run.file_hash}.pdf", media_type="application/pdf")


@app.get("/api/runs/{run_id}/pages/{n}")
async def run_page(run_id: str, n: int):
    async with Session() as s:
        run = await s.get(Run, run_id)
    path = settings.PAGE_IMAGE_DIR / (run.file_hash if run else "_") / f"page-{n}.png"
    if not run or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


@app.post("/api/runs/{run_id}/review", response_model=RunSummary)
async def review_run(run_id: str, body: ReviewIn) -> RunSummary:
    """A person settles an invoice the pipeline held. Approval makes it count against the PO balance."""
    async with Session() as s:
        run = await s.get(Run, run_id)
        if not run or run.decision != "needs_review":
            raise HTTPException(409, "Only invoices held for review can be reviewed")
        run.reviewer_action, run.reviewer_note, run.reviewed_at = body.action, body.note, utcnow()
        ledger = await s.get(LedgerInvoice, run_id)
        if ledger:
            ledger.status = body.action
        await s.commit()
        return _summary(run)


@app.get("/api/stats", response_model=Stats)
async def stats() -> Stats:
    async with Session() as s:
        rows = (await s.execute(select(Run.status, Run.decision, Run.reviewer_action, Run.total, Run.currency))).all()
    final = lambda r: r.reviewer_action or r.decision  # noqa: E731
    done = [r for r in rows if r.status == "completed"]
    return Stats(
        total=len(rows),
        approved=sum(final(r) == "approved" for r in done),
        needs_review=sum(final(r) == "needs_review" for r in done),
        rejected=sum(final(r) == "rejected" for r in done),
        running=sum(r.status in ("queued", "running") for r in rows),
        failed=sum(r.status == "failed" for r in rows),
        approved_amounts=_by_currency([r for r in done if final(r) == "approved"]),
        held_amounts=_by_currency([r for r in done if final(r) == "needs_review"]),
    )


def _by_currency(rows) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows:
        cur = (r.currency or "USD").upper()
        out[cur] = round(out.get(cur, 0) + (r.total or 0), 2)
    return out


# ------------------------------------------------------------------ master data + demo helpers
@app.get("/api/master")
async def master() -> dict[str, Any]:
    async with Session() as s:
        vendors = (await s.scalars(select(Vendor))).all()
        pos = (await s.scalars(select(PurchaseOrder))).all()
        lines = (await s.scalars(select(POLine).order_by(POLine.line_no))).all()
        billed = dict((await s.execute(select(LedgerInvoice.po_number, func.sum(LedgerInvoice.net_amount))
                                       .where(LedgerInvoice.status == "approved")
                                       .group_by(LedgerInvoice.po_number))).all())
    return {
        "vendors": [{k: getattr(v, k) for k in ("vendor_id", "name", "tax_id", "country", "currency", "bank_name",
                                                "bank_account", "status")} for v in vendors],
        "purchase_orders": [{
            "po_number": p.po_number, "vendor_id": p.vendor_id, "currency": p.currency, "status": p.status,
            "description": p.description, "issue_date": p.issue_date.isoformat(),
            "total": round(sum(l.quantity * l.unit_price for l in lines if l.po_number == p.po_number), 2),
            "invoiced": round(billed.get(p.po_number) or 0, 2),
            "lines": [{"line_no": l.line_no, "sku": l.sku, "description": l.description, "quantity": l.quantity,
                       "unit_price": l.unit_price} for l in lines if l.po_number == p.po_number],
        } for p in pos],
    }


@app.get("/api/samples", response_model=list[str])
async def samples() -> list[str]:
    return sorted(p.name for p in SAMPLES_DIR.glob("*.pdf"))


@app.post("/api/samples/{name}/run", response_model=RunSummary)
async def run_sample(name: str) -> RunSummary:
    path = (SAMPLES_DIR / name).resolve()
    if path.parent != SAMPLES_DIR.resolve() or not path.exists():
        raise HTTPException(404, "Sample not found")
    return await _start(name, path.read_bytes())


async def _clear_history() -> None:
    if _tasks:
        raise HTTPException(409, "Wait for running invoices to finish")
    async with Session() as s:
        for model in (RunEvent, LedgerInvoice, Run):
            await s.execute(delete(model))
        await s.commit()


@app.post("/api/reset")
async def reset() -> dict[str, str]:
    """Demo helper: clears runs and the invoice ledger (master data stays)."""
    await _clear_history()
    return {"status": "ok"}


async def _run_batch(names: list[str]) -> None:
    """One sample at a time, each to completion: later samples (split PO, re-sent duplicate) depend on the
    ledger the earlier ones leave behind, so starting them together would make the outcomes order-dependent."""
    for name in names:
        summary = await _start(name, (SAMPLES_DIR / name).read_bytes())
        while True:
            run_tasks = [t for t in _tasks if t.get_name() == summary.id]
            if not run_tasks:
                break
            await asyncio.wait(run_tasks)


@app.post("/api/samples/batch", response_model=list[str])
async def run_sample_batch() -> list[str]:
    """Demo helper: clear history, then run every sample in file order. Returns the order it will run in."""
    names = sorted(p.name for p in SAMPLES_DIR.glob("*.pdf"))
    if not names:
        raise HTTPException(404, "No sample invoices")
    await _clear_history()
    task = asyncio.create_task(_run_batch(names), name="sample-batch")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return names


if FRONTEND_DIST.exists():  # single-process deploy: serve the built UI
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        return FileResponse(dist_file(FRONTEND_DIST, path))


def dist_file(root: Path, path: str) -> Path:
    """The built-UI file for a URL path, else index.html (client-side routes). Resolved first, then required to
    stay inside the UI folder: "../" or "%2e%2e" must never reach the .env, the database or uploaded invoices."""
    root = root.resolve()
    f = (root / path).resolve()
    return f if path and f.is_relative_to(root) and f.is_file() else root / "index.html"
