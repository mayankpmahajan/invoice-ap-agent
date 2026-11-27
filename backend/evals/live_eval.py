"""Opt-in live eval (never run by pytest): each selected case's invoice goes to the REAL models through the real
pipeline, in a throwaway database; its prior invoices replay their recorded answers so only the invoice under test
costs model calls. Compares the model's extraction with the ground truth and the decision with the expected one,
and writes a results JSON.

Every case makes 1 vision call plus 0-2 matcher calls. Run one case at a time while deciding anything, and only one
model-calling process at once.

Usage (from backend/):
  uv run python -m evals.live_eval --case happy_clean_digital
  uv run python -m evals.live_eval --case duplicate --case price_   # every id containing either string
  uv run python -m evals.live_eval --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_WORK = Path(tempfile.mkdtemp(prefix="ap-live-eval-"))
os.environ.setdefault("DATA_DIR", str(_WORK / "app"))  # set before any app import: never the app's real data folder

from evals.runner import CASES_DIR, compare, load_cases, run_case  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
TEXT_FIELDS = ("vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "po_reference")
ID_FIELDS = ("vendor_tax_id", "vendor_bank_account")  # compared on letters and digits only
AMOUNT_FIELDS = ("subtotal", "tax_amount", "total")


def _norm_text(v):
    return None if v is None else " ".join(str(v).split()).casefold()


def _norm_id(v):
    return None if v is None else re.sub(r"[^A-Z0-9]", "", str(v).upper()) or None


def _same_id(a, b) -> bool:
    """Same account / tax number even when one side keeps a bank name or label ("Wells Fargo, routing ...")."""
    na, nb = _norm_id(a), _norm_id(b)
    return na == nb or bool(na and nb and (na.endswith(nb) or nb.endswith(na)))


def _same_amount(a, b) -> bool:
    return (a is None) == (b is None) and (a is None or abs(a - b) <= 0.01)


def diff_extraction(truth: dict | None, got: dict | None) -> dict:
    """Value differences (what changes outcomes) and confidence differences (what changes routing on scans)."""
    if truth is None or got is None:
        return {"values": [] if truth is got else [{"field": "extraction", "expected": truth is not None,
                                                     "got": got is not None}], "confidence": []}
    values, conf = [], []

    def add(name, want, have):
        values.append({"field": name, "expected": want, "got": have})

    if truth["document_type"] != got["document_type"]:
        add("document_type", truth["document_type"], got["document_type"])
    if truth["amounts_include_tax"] != got["amounts_include_tax"]:
        add("amounts_include_tax", truth["amounts_include_tax"], got["amounts_include_tax"])
    for f in TEXT_FIELDS + ID_FIELDS + AMOUNT_FIELDS:
        want, have = truth[f]["value"], got[f]["value"]
        same = (_same_amount(want, have) if f in AMOUNT_FIELDS
                else _same_id(want, have) if f in ID_FIELDS else _norm_text(want) == _norm_text(have))
        if not same:
            add(f, want, have)
        if truth[f]["confidence"] != got[f]["confidence"]:
            conf.append({"field": f, "expected": truth[f]["confidence"], "got": got[f]["confidence"]})
    tl, gl = truth["line_items"], got["line_items"]
    if len(tl) != len(gl):
        add("line_items.count", len(tl), len(gl))
    for i, (t, g) in enumerate(zip(tl, gl)):
        for k in ("quantity", "unit_price", "amount"):
            if not _same_amount(t[k], g[k]):
                add(f"line_items[{i}].{k}", t[k], g[k])
        if _norm_id(t["sku"]) != _norm_id(g["sku"]):
            add(f"line_items[{i}].sku", t["sku"], g["sku"])
    return {"values": values, "confidence": conf}


async def _run(cases: list[dict]) -> list[dict]:
    out = []
    for case in cases:  # sequential: one model call in flight per case, one process
        subject = case["steps"][-1]
        started = time.monotonic()
        try:
            results = await run_case(case, CASES_DIR / case["id"], _WORK / case["id"], live=True)
        except Exception as e:  # noqa: BLE001 - one broken case is recorded, the rest still run
            out.append({"case": case["id"], "error": f"{type(e).__name__}: {e}"})
            print(f"{case['id']}: ERROR {type(e).__name__}: {e}", flush=True)
            continue
        res = results[-1]
        mismatches = [p for step, r in zip(case["steps"], results) for p in compare(step["expected"], r)]
        calls = [{k: c.get(k) for k in ("role", "model", "latency_ms", "input_tokens", "output_tokens", "attempts")}
                 for c in res["llm_calls"]]
        row = {
            "case": case["id"], "scenario": case["scenario"], "known_gap": case.get("xfail"),
            "expected_decision": subject["expected"]["decision"], "decision": res["decision"],
            "status": res["status"], "error": res["error"],
            "decision_match": res["decision"] == subject["expected"]["decision"]
            and res["status"] == subject["expected"]["status"],
            "outcome_mismatches": mismatches,
            "expected_checks": subject["expected"]["checks"],
            "checks": {k: v for k, v in res["checks"].items() if v != "pass"},
            "extraction_diff": diff_extraction(subject["extraction"], res["extraction"]),
            "model_extraction": res["extraction"],
            "match": res["match"], "llm_calls": calls,
            "model_latency_ms": sum(c["latency_ms"] or 0 for c in calls),
            "wall_seconds": round(time.monotonic() - started, 1),
        }
        out.append(row)
        print(f"{case['id']}: {res['decision']} (expected {row['expected_decision']}) "
              f"{'MATCH' if row['decision_match'] else 'MISMATCH'}; "
              f"{len(row['extraction_diff']['values'])} extraction value diffs; "
              f"model {row['model_latency_ms']} ms", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Live eval of dataset cases against the real models.")
    ap.add_argument("--case", action="append", help="run cases whose id contains this text (repeatable)")
    ap.add_argument("--all", action="store_true", help="run every case")
    ap.add_argument("--out", type=Path, help="results JSON (default evals/results/live-<utc time>.json)")
    args = ap.parse_args()
    if not args.case and not args.all:
        ap.error("pick cases with --case (or --all): every case costs real model calls")
    cases = load_cases(None if args.all else args.case)
    if not cases:
        ap.error("no case id matches")

    from app import settings
    if not settings.LLM_API_KEY:
        sys.exit("OPENROUTER_API_KEY is not set (backend/.env); the live eval needs it.")

    rows = asyncio.run(_run(cases))
    out = args.out or RESULTS_DIR / f"live-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "models": {"vision": settings.VISION_MODEL_NAME, "generator": settings.GENERATOR_MODEL_NAME,
                   "critique": settings.CRITIQUE_MODEL_NAME},
        "pipeline_git_sha": settings.PIPELINE_GIT_SHA, "cases": rows,
        "summary": {"cases": len(rows), "decision_match": sum(bool(r.get("decision_match")) for r in rows),
                    "errors": sum("decision" not in r for r in rows)}}, indent=1, default=str) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
