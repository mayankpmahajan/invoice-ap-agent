"""The invoice pipeline: a fixed sequence of stages, each persisted as events the UI streams live.

  ingest -> extract (1 vision call) -> verify -> match (fast path, else 1 generator call,
  + 1 critique call only if unsure) -> duplicate -> po_checks -> decision
"""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from app import llm, rules, settings
from app.db import LedgerInvoice, POLine, PurchaseOrder, Run, RunEvent, Session, Vendor, utcnow
from app.pdf import IngestedPdf, ingest, normalize_ws, quote_in_text_layer
from app.schemas import InvoiceExtraction, MatchDecision

STAGES = [
    ("ingest", "Read the PDF"),
    ("extract", "Extract invoice fields"),
    ("verify", "Verify extraction"),
    ("match", "Match vendor and PO"),
    ("duplicate", "Duplicate check"),
    ("po_checks", "Compare against PO"),
    ("decision", "Decision"),
]


async def emit(run_id: str, stage: str, status: str, title: str, data: dict[str, Any] | None = None) -> None:
    async with Session() as s:
        s.add(RunEvent(run_id=run_id, stage=stage, status=status, title=title,
                       data=json.loads(json.dumps(data, default=str)) if data else None))
        run = await s.get(Run, run_id)
        run.current_stage = stage
        if run.status == "queued":
            run.status = "running"
        await s.commit()


# ------------------------------------------------------------------ data loading
async def load_master() -> tuple[list[rules.VendorRec], list[rules.PORec]]:
    async with Session() as s:
        vendors = [rules.VendorRec(v.vendor_id, v.name, v.tax_id, v.bank_account, v.status, v.currency)
                   for v in (await s.scalars(select(Vendor))).all()]
        lines = (await s.scalars(select(POLine).order_by(POLine.po_number, POLine.line_no))).all()
        pos = []
        for po in (await s.scalars(select(PurchaseOrder))).all():
            pos.append(rules.PORec(po.po_number, po.vendor_id, po.currency, po.status, [
                rules.POLineRec(f"{l.po_number}#{l.line_no}", l.sku, l.description, l.quantity, l.unit_price)
                for l in lines if l.po_number == po.po_number], po.issue_date))
    return vendors, pos


async def load_ledger(exclude_run: str) -> list[rules.LedgerRec]:
    async with Session() as s:
        rows = (await s.scalars(select(LedgerInvoice).where(LedgerInvoice.run_id != exclude_run))).all()
    return [rules.LedgerRec(r.run_id, r.vendor_id, r.invoice_number, r.invoice_number_norm, r.invoice_date, r.total,
                            r.net_amount, r.po_number, r.file_hash, r.status, r.po_line_quantities or {}) for r in rows]


# ------------------------------------------------------------------ verify
def _value_variants(field: str, ex: InvoiceExtraction) -> list[str]:
    v = getattr(ex, field).value
    if v is None:
        return []
    if isinstance(v, float):
        return [f"{v:,.2f}", f"{v:.2f}"]
    return [str(v)]


def verify_against_text_layer(ex: InvoiceExtraction, ing: IngestedPdf) -> dict[str, bool]:
    """Quote found verbatim on its page, or (fallback) the value itself printed on some page. Exact, never fuzzy."""
    all_text = " ".join(p.text for p in ing.pages)
    out: dict[str, bool] = {}
    for f in settings.CRITICAL_FIELDS + ("po_reference", "vendor_bank_account", "subtotal", "tax_amount"):
        fld = getattr(ex, f)
        if fld.value is None:
            continue
        page_text = next((p.text for p in ing.pages if p.number == fld.page), all_text)
        out[f] = quote_in_text_layer(fld.quote, page_text) or any(
            normalize_ws(x) in normalize_ws(all_text) for x in _value_variants(f, ex))
        if f in ("invoice_date", "currency") and not out[f]:
            out[f] = quote_in_text_layer(fld.quote, all_text)  # normalised values (ISO date, ISO code) rely on the quote
    return out


# ------------------------------------------------------------------ match
def _norm_name(s: str | None) -> str:
    s = re.sub(r"[^a-z0-9 ]", "", (s or "").lower())
    return " ".join(w for w in s.split() if w not in {"inc", "llc", "ltd", "co", "corp", "corporation", "limited", "company"})


def fast_match(ex: InvoiceExtraction, vendors: list[rules.VendorRec], pos: list[rules.PORec]
               ) -> tuple[rules.VendorRec | None, rules.PORec | None, list[str | None], bool]:
    """Exact identifiers only. Returns (vendor, po, line_map, complete) - complete means no model call needed."""
    tax = rules.norm_account(ex.vendor_tax_id.value)
    vendor = next((v for v in vendors if tax and rules.norm_account(v.tax_id) == tax), None) or next(
        (v for v in vendors if _norm_name(v.name) == _norm_name(ex.vendor_name.value)), None)
    cited = rules.norm_account(ex.po_reference.value)
    po = next((p for p in pos if cited and rules.norm_account(p.po_number) == cited), None)
    line_map: list[str | None] = []
    for li in ex.line_items:
        hit = None
        if po:
            hit = next((l.id for l in po.lines if li.sku and l.sku and l.sku.upper() == li.sku.upper()), None) or next(
                (l.id for l in po.lines if normalize_ws(l.description.lower()) == normalize_ws(li.description.lower())), None)
        line_map.append(hit)
    complete = bool(vendor and po and po.vendor_id == vendor.vendor_id and all(line_map))
    return vendor, po, line_map, complete


def _match_context(vendors: list[rules.VendorRec], pos: list[rules.PORec], ledger: list[rules.LedgerRec]):
    """Short ids for the model (V1, P1, L1) mapped back to real ids afterwards."""
    vid = {f"V{i}": v for i, v in enumerate(vendors, 1)}
    v_short = {v.vendor_id: k for k, v in vid.items()}
    pid, lid, po_lines = {}, {}, []
    n = 0
    for i, p in enumerate([p for p in pos if p.status == "open"], 1):
        pid[f"P{i}"] = p
        billed = sum(r.net_amount or 0 for r in ledger if r.po_number == p.po_number and r.status == "approved")
        po_lines.append(f"P{i} | {p.po_number} | vendor {v_short[p.vendor_id]} | {p.currency} | total {p.total} | "
                        f"already invoiced {billed}")
        for l in p.lines:
            n += 1
            lid[f"L{n}"] = l.id
            po_lines.append(f"  L{n} | sku {l.sku or '-'} | {l.description} | qty {l.quantity:g} @ {l.unit_price}")
    vendors_block = "\n".join(f"{k} | {v.name} | tax id {v.tax_id} | {v.status}" for k, v in vid.items())
    return vid, pid, lid, vendors_block, "\n".join(po_lines)


async def model_match(ex: InvoiceExtraction, vendors, pos, ledger, calls: list[dict]) -> tuple[
        rules.VendorRec | None, rules.PORec | None, list[str | None], MatchDecision, str]:
    vid, pid, lid, vblock, pblock = _match_context(vendors, pos, ledger)
    inv = ex.model_dump_json(include={"vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "currency",
                                      "po_reference", "line_items", "subtotal", "total"})
    decision, rec = await llm.match_invoice("generator", inv, vblock, pblock)
    calls.append(rec.as_dict())
    settled_by = "generator"
    if decision.confidence != "sure":
        # Confidence-gated help: a different model answers fresh, seeing only the doubt, never the first answer.
        decision, rec = await llm.match_invoice("critique", inv, vblock, pblock, doubt=decision.doubt_reason)
        calls.append(rec.as_dict())
        settled_by = "critique"
    line_map = [lid.get(x) for x in decision.line_matches]
    line_map = (line_map + [None] * len(ex.line_items))[: len(ex.line_items)]
    return vid.get(decision.vendor_id), pid.get(decision.po_id), line_map, decision, settled_by


# ------------------------------------------------------------------ run
async def run_pipeline(run_id: str, pdf_bytes: bytes) -> None:
    async with settings.RUN_SEMAPHORE:
        try:
            await _run(run_id, pdf_bytes)
        except Exception as e:  # noqa: BLE001 - terminal state must be persisted, then the error surfaced in the UI
            async with Session() as s:
                run = await s.get(Run, run_id)
                run.status, run.error, run.finished_at = "failed", f"{type(e).__name__}: {e}", utcnow()
                await s.commit()
            await emit(run_id, run.current_stage or "ingest", "failed", "Run failed",
                       {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]})


async def _run(run_id: str, pdf_bytes: bytes) -> None:
    started = datetime.now(timezone.utc)
    calls: list[dict] = []

    await emit(run_id, "ingest", "started", "Reading PDF")
    ing = ingest(pdf_bytes)
    await emit(run_id, "ingest", "completed", f"{len(ing.pages)} page(s), {ing.kind} PDF", {
        "pages": len(ing.pages), "kind": ing.kind, "sha256": ing.sha256,
        "text_layer_chars": [len(p.text.strip()) for p in ing.pages]})

    await emit(run_id, "extract", "started", f"Reading invoice with {settings.VISION_MODEL_NAME}")
    ex, rec = await llm.extract_invoice(ing.pages)
    calls.append(rec.as_dict())
    await emit(run_id, "extract", "completed", f"Extracted {len(ex.line_items)} line(s)",
               {"extraction": ex.model_dump(), "call": {k: rec.as_dict()[k] for k in
                ("model", "prompt_ref", "latency_ms", "input_tokens", "output_tokens", "attempts")}})

    await emit(run_id, "verify", "started", "Checking extraction against the PDF")
    verified = verify_against_text_layer(ex, ing) if ing.kind == "digital" else {}
    checks = [rules.check_document_type(ex), rules.check_required_fields(ex),
              rules.check_grounding(ex, verified, ing.kind == "digital"), rules.check_arithmetic(ex)]
    await emit(run_id, "verify", "completed", "Extraction verified", {"checks": [c.__dict__ for c in checks]})
    await _pace()

    # Nothing to match: a non-invoice is void, an unreadable document is held for a person (document_type check).
    if ex.document_type in ("not_an_invoice", "unreadable"):
        return await _finish(run_id, ing, ex, checks, None, None, [], calls, started, {"how": "skipped"})

    await emit(run_id, "match", "started", "Matching vendor and purchase order")
    vendors, pos = await load_master()
    ledger = await load_ledger(run_id)
    vendor, po, line_map, complete = fast_match(ex, vendors, pos)
    match_info: dict[str, Any] = {"how": "exact identifiers", "llm": False}
    how = "cited"
    if not complete:
        vendor, po, line_map, decision, settled_by = await model_match(ex, vendors, pos, ledger, calls)
        how = "cited" if ex.po_reference.value and po and rules.norm_account(po.po_number) == rules.norm_account(
            ex.po_reference.value) else "inferred"
        match_info = {"how": "model", "llm": True, "settled_by": settled_by, "confidence": decision.confidence,
                      "doubt": decision.doubt_reason}
    else:
        decision = None
    match_checks = [rules.check_vendor(vendor, ex), rules.check_tax_id(vendor, ex), rules.check_bank_details(vendor, ex),
                    rules.check_po(po, vendor.vendor_id if vendor else None, ex, how,
                                   decision.confidence if decision else "sure",
                                   decision.doubt_reason if decision else None),
                    rules.check_dates(ex, po, date.today())]
    match_checks = [c for c in match_checks if c is not None]
    checks += match_checks
    match_info.update({"vendor": vendor.__dict__ if vendor else None, "po_number": po.po_number if po else None,
                       "po_how": how, "line_map": line_map})
    await emit(run_id, "match", "completed",
               f"{vendor.name if vendor else 'Unknown vendor'} / {po.po_number if po else 'no PO'}",
               {**match_info, "checks": [c.__dict__ for c in match_checks]})
    await _pace()

    await emit(run_id, "duplicate", "started", "Searching processed invoices")
    dup = rules.check_duplicate(ex, vendor.vendor_id if vendor else None, ing.sha256, ledger)
    checks.append(dup)
    await emit(run_id, "duplicate", "completed", dup.detail, {"checks": [dup.__dict__], "ledger_size": len(ledger)})
    await _pace()

    await emit(run_id, "po_checks", "started", "Comparing prices, quantities and PO balance")
    if dup.outcome == "reject":
        # A duplicate is void whatever the PO says; comparing it would count its own original against the
        # balance and add a misleading over-billing hold next to the real reason.
        await emit(run_id, "po_checks", "skipped", "Not compared: this invoice is a duplicate",
                   {"checks": [], "duplicate": True})
        return await _finish(run_id, ing, ex, checks, vendor, po, line_map, calls, started, match_info)
    po_checks = rules.check_lines_against_po(po, ex, line_map, ledger)
    cur = rules.check_currency(po, ex)
    po_checks = ([cur] if cur else []) + po_checks
    checks += po_checks
    await emit(run_id, "po_checks", "completed" if po else "skipped",
               "PO comparison done" if po else "No PO to compare against",
               {"checks": [c.__dict__ for c in po_checks],
                "po": {"po_number": po.po_number, "total": po.total, "currency": po.currency,
                       "lines": [l.__dict__ for l in po.lines]} if po else None})
    await _pace()

    await _finish(run_id, ing, ex, checks, vendor, po, line_map, calls, started, match_info)


async def _pace() -> None:
    """The checks after the read finish in milliseconds; a short pause lets a person watching the live view see
    each stage land instead of five at once. Display only: no result depends on it (0 disables)."""
    if settings.STAGE_MIN_VISIBLE_SECONDS > 0:
        await asyncio.sleep(settings.STAGE_MIN_VISIBLE_SECONDS)


async def _finish(run_id, ing, ex, checks, vendor, po, line_map, calls, started, match_info) -> None:
    decision, headline, details = rules.decide(checks)
    summary = f"{headline}. {details}"
    provenance = {"file_sha256": ing.sha256, "pipeline_git_sha": settings.PIPELINE_GIT_SHA,
                  "started_at": started.isoformat(), "finished_at": utcnow().isoformat(), "llm_calls": calls}
    line_qty: dict[str, float] = {}
    for li, lid in zip(ex.line_items, line_map):
        if lid:
            line_qty[lid] = line_qty.get(lid, 0) + (li.quantity or 0)
    async with Session() as s:
        run = await s.get(Run, run_id)
        run.status, run.decision, run.decision_summary, run.finished_at = "completed", decision, summary, utcnow()
        run.pdf_kind, run.vendor_name = ing.kind, vendor.name if vendor else ex.vendor_name.value
        run.invoice_number, run.total, run.currency = ex.invoice_number.value, ex.total.value, ex.currency.value
        run.po_number = po.po_number if po else ex.po_reference.value
        run.result = json.loads(json.dumps({
            "decision": decision, "headline": headline, "summary": details, "checks": [c.__dict__ for c in checks],
            "extraction": ex.model_dump(), "match": match_info, "provenance": provenance,
            "page_count": len(ing.pages)}, default=str))
        s.add(LedgerInvoice(run_id=run_id, vendor_id=vendor.vendor_id if vendor else None,
                            invoice_number=ex.invoice_number.value,
                            invoice_number_norm=rules.norm_invoice_number(ex.invoice_number.value),
                            invoice_date=rules.parse_date(ex.invoice_date.value), total=ex.total.value,
                            net_amount=rules.net_amount(ex), currency=ex.currency.value,
                            po_number=po.po_number if po else None, file_hash=ing.sha256, status=decision,
                            po_line_quantities=line_qty))
        # The decision event is written in the same commit as the completed status, so a stream that sees the
        # run completed never ends before the decision event exists.
        run.current_stage = "decision"
        s.add(RunEvent(run_id=run_id, stage="decision", status="completed", title=headline,
                       data={"decision": decision, "headline": headline, "summary": details,
                             "counts": {o: sum(c.outcome == o for c in checks) for o in ("pass", "info", "review", "reject")}}))
        await s.commit()
