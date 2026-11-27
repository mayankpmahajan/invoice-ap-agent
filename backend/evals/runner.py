"""Runs one eval case through the REAL pipeline - upload (app.main._start), ingest, verify against the text layer,
fast match, rules, decision, ledger writes, reviewer actions - in its own SQLite database and data folder.

Only the model calls are replaced: the vision call returns the case's ground-truth extraction and the matcher
returns the answer recorded in the case (translated to the short ids the real prompt context uses). In live mode
the invoice under test goes to the real models instead; its priors still replay their recorded answers.

The app's settings, engine and session factory are module globals, so the harness swaps them for the duration of
one case and restores them afterwards. It refuses to run against the app's default data folder.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "cases"


def load_cases(only: list[str] | None = None) -> list[dict]:
    """Every case.json under evals/cases, optionally only those whose id contains one of `only`."""
    cases = [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*/case.json"))]
    if only:
        cases = [c for c in cases if any(o in c["id"] for o in only)]
    return cases


@asynccontextmanager
async def _isolated_app(data_dir: Path, as_of: date):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app import db, settings

    data_dir = data_dir.resolve()
    live_data = (settings.BACKEND_DIR / "data").resolve()
    if data_dir == live_data or live_data in data_dir.parents:
        raise RuntimeError(f"refusing to run an eval case inside the app's data folder {live_data}")
    for d in (data_dir, data_dir / "uploads", data_dir / "pages"):
        d.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{data_dir / 'ap.db'}")
    session = async_sessionmaker(engine, expire_on_commit=False)

    class _Today(date):
        @classmethod
        def today(cls) -> date:  # the case's "as of" day, so date checks never age
            return date(as_of.year, as_of.month, as_of.day)

    patches: list[tuple[Any, str, Any]] = [
        (settings, "DATA_DIR", data_dir), (settings, "UPLOAD_DIR", data_dir / "uploads"),
        (settings, "PAGE_IMAGE_DIR", data_dir / "pages"), (settings, "STAGE_MIN_VISIBLE_SECONDS", 0),
        (db, "engine", engine), (db, "Session", session)]
    # Every app module that imported the session factory by name gets the isolated one.
    patches += [(mod, "Session", session) for name, mod in list(sys.modules.items())
                if name.startswith("app.") and mod is not db and getattr(mod, "Session", None) is db.Session]
    from app import pipeline
    patches.append((pipeline, "date", _Today))
    saved = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in patches]
    try:
        for obj, attr, value in patches:
            setattr(obj, attr, value)
        yield session
    finally:
        for obj, attr, value in reversed(saved):
            setattr(obj, attr, value)
        await engine.dispose()


async def _apply_master_patch(session, patch: dict | None) -> None:
    if not patch:
        return
    from sqlalchemy import update

    from app.db import PurchaseOrder, Vendor
    tables = {"purchase_orders": (PurchaseOrder, PurchaseOrder.po_number), "vendors": (Vendor, Vendor.vendor_id)}
    async with session() as s:
        for table, rows in patch.items():
            model, key = tables[table]
            for row_id, values in rows.items():
                res = await s.execute(update(model).where(key == row_id).values(**values))
                if res.rowcount != 1:
                    raise ValueError(f"master_patch: no {table} row {row_id}")
        await s.commit()


async def _short_ids(answer: dict):
    """A recorded matcher answer (real ids) in the short ids the real prompt context hands the model."""
    from app import pipeline
    from app.schemas import MatchDecision

    vendors, pos = await pipeline.load_master()
    vid, pid, lid, _, _ = pipeline._match_context(vendors, pos, [])
    v_short = {v.vendor_id: k for k, v in vid.items()}
    p_short = {p.po_number: k for k, p in pid.items()}
    l_short = {real: k for k, real in lid.items()}

    def short(table: dict, real: str, what: str) -> str:
        if real == "none":
            return "none"
        if real not in table:
            raise ValueError(f"recorded matcher answer names {what} {real}, which the matcher is never offered")
        return table[real]

    return MatchDecision(vendor_id=short(v_short, answer["vendor_id"], "vendor"),
                         po_id=short(p_short, answer["po_number"], "open PO"),
                         line_matches=[short(l_short, x, "PO line") for x in answer["lines"]],
                         confidence=answer["confidence"], doubt_reason=answer["doubt"])


async def _read_run(session, run_id: str) -> dict:
    from app.db import Run
    async with session() as s:
        run = await s.get(Run, run_id)
    result = run.result or {}
    checks = result.get("checks", [])
    ids = [c["id"] for c in checks]
    if len(ids) != len(set(ids)):
        raise AssertionError(f"run {run_id} produced the same check id twice: {ids}")
    return {"run_id": run_id, "status": run.status, "decision": run.decision, "error": run.error,
            "checks": {c["id"]: c["outcome"] for c in checks}, "details": {c["id"]: c["detail"] for c in checks},
            "match": result.get("match"), "extraction": result.get("extraction"),
            "llm_calls": (result.get("provenance") or {}).get("llm_calls", [])}


async def run_case(case: dict, case_dir: Path, data_dir: Path, live: bool = False) -> list[dict]:
    """Runs every step of the case in order; returns one result per step (priors first)."""
    from app import db, llm, main
    from app.schemas import InvoiceExtraction

    state: dict[str, Any] = {}
    real_extract, real_match = llm.extract_invoice, llm.match_invoice

    def _live_now() -> bool:
        return live and state["step"]["role"] == "subject"

    async def extract(pages):
        if _live_now():
            return await real_extract(pages)
        step = state["step"]
        if step["extraction"] is None:
            raise AssertionError(f"{case['id']}/{step['file']}: pipeline asked for an extraction the case does not have")
        ex = InvoiceExtraction.model_validate(step["extraction"])
        return ex, llm.CallRecord(role="vision", model="stub:ground-truth", prompt_ref="stub", params={},
                                  attempts=1, output=ex.model_dump())

    async def match(role, invoice_json, vendors_block, pos_block, doubt=None):
        if _live_now():
            return await real_match(role, invoice_json, vendors_block, pos_block, doubt)
        step = state["step"]
        answer = (step.get("matcher") or {}).get(role)
        if answer is None:
            raise AssertionError(f"{case['id']}/{step['file']}: the pipeline asked the {role} matcher, but the case "
                                 f"records no {role} answer")
        decision = await _short_ids(answer)
        return decision, llm.CallRecord(role=role, model="stub:recorded", prompt_ref="stub", params={}, attempts=1,
                                        output=decision.model_dump())

    results = []
    async with _isolated_app(data_dir, date.fromisoformat(case["as_of"])) as session:
        saved = (llm.extract_invoice, llm.match_invoice)
        llm.extract_invoice, llm.match_invoice = extract, match
        try:
            await db.init_db()
            await _apply_master_patch(session, case.get("master_patch"))
            for step in case["steps"]:
                state["step"] = step
                summary = await main._start(step["file"], (case_dir / step["file"]).read_bytes())
                await asyncio.gather(*[t for t in list(main._tasks) if t.get_name() == summary.id])
                if step.get("review"):
                    await main.review_run(summary.id, main.ReviewIn(action=step["review"], note="eval case setup"))
                results.append(await _read_run(session, summary.id))
        finally:
            llm.extract_invoice, llm.match_invoice = saved
    return results


def compare(expected: dict, result: dict) -> list[str]:
    """Differences between a step's expected outcome and what the pipeline did; empty when they agree."""
    problems = []
    if result["status"] != expected["status"]:
        problems.append(f"status {result['status']!r} (error: {result['error']}), expected {expected['status']!r}")
        return problems
    if result["decision"] != expected["decision"]:
        problems.append(f"decision {result['decision']!r}, expected {expected['decision']!r}")
    if expected["status"] == "completed":
        got = {k: v for k, v in result["checks"].items() if v != "pass"}
        if got != expected["checks"]:
            problems.append(f"non-pass checks {got}, expected {expected['checks']}")
        m = result["match"] or {}
        actual = {"how": m.get("how"), "settled_by": m.get("settled_by"), "po": m.get("po_number"),
                  "vendor": (m.get("vendor") or {}).get("vendor_id"), "po_how": m.get("po_how")}
        for key, want in actual.items():
            if expected.get(key) is not None and want != expected[key]:
                problems.append(f"match {key} {want!r}, expected {expected[key]!r}")
    return problems
