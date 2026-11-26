"""Probe: confirms the vision json_schema path and the pydantic-ai NativeOutput path work on the configured models."""
import asyncio, sys
from pathlib import Path
from app import llm, settings
from app.pdf import ingest

async def main(pdf: str, role: str):
    ing = ingest(Path(pdf).read_bytes())
    ex, rec = await llm.extract_invoice(ing.pages)
    print("VISION", rec.model, ing.kind, rec.finish_reason, rec.attempts, rec.input_tokens, rec.output_tokens, rec.latency_ms, rec.validation_errors[:1])
    print(" ", ex.document_type, ex.vendor_name.value, ex.invoice_number.value, ex.po_reference.value, ex.total.value, ex.total.confidence, len(ex.line_items))
    m, r2 = await llm.match_invoice(role, ex.model_dump_json(), "V1 | Brightline Logistics LLC | tax 46-7788990", "P1 (PO-2026-0461) FTL Chicago to Dallas\n  L1 FTL shipment Chicago IL to Dallas TX qty 12 @1850\nP2 (PO-2026-0470) LTL Midwest\n  L2 LTL per pallet qty 40 @165")
    print("MATCH", r2.model, r2.attempts, r2.input_tokens, r2.output_tokens, r2.latency_ms, m)

asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "generator"))
