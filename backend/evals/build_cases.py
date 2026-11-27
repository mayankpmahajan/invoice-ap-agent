"""Rebuild the eval dataset from evals/catalogue.py: one folder per case with case.json and its PDFs.

Deterministic (reportlab invariant=1, scans with pinned PDF dates), so a rebuild that changes no case changes no byte.
Every ground-truth quote is checked against the text the PDF printed (for scans: the page before scanning), so a
case whose truth and PDF disagree fails the build instead of being written.

Usage: uv run python -m evals.build_cases [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ap-evals-build-"))  # app import never touches backend/data

import pypdfium2 as pdfium  # noqa: E402

from app.pdf import IngestedPdf, Page  # noqa: E402
from evals.catalogue import CASES, Case, Match  # noqa: E402
from evals.dataset import check_quotes, ground_truth, page_texts, render  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"


def _match(m: Match | None) -> dict | None:
    if m is None:
        return None
    return {"vendor_id": m.vendor, "po_number": m.po, "lines": m.lines, "confidence": m.confidence, "doubt": m.doubt}


def _pdf_kind(pdf: bytes) -> str:
    """digital | scanned | mixed by the pipeline's own rule (app.pdf.IngestedPdf.kind), or broken."""
    try:
        texts = page_texts(pdf)
    except pdfium.PdfiumError:
        return "broken"
    return IngestedPdf("", [Page(i, Path(), t) for i, t in enumerate(texts, 1)]).kind


def build_case(case: Case, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(exist_ok=True)
    steps = []
    n = len(case.steps)
    for i, step in enumerate(case.steps, 1):
        name = "invoice.pdf" if i == n else f"prior_{i}.pdf"
        source, image_only = render(step.doc, out / name, work)
        truth = ground_truth(step.doc)
        pdf = (out / name).read_bytes()
        if truth is not None:
            problems = check_quotes(truth, page_texts(source), image_only)
            if problems:
                raise ValueError(f"{case.id}/{name}: ground truth does not match the printed PDF: {problems}")
        steps.append({
            "file": name, "role": "subject" if i == n else "prior", "pdf_kind": _pdf_kind(pdf),
            "image_only_fields": image_only, "extraction": truth,
            "matcher": ({"generator": _match(step.generator), "critique": _match(step.critique)}
                        if step.generator or step.critique else None),
            "review": step.review, "expected": asdict(step.expect)})
    shutil.rmtree(work)
    doc = {"id": case.id, "scenario": case.scenario, "branch": case.branch, "ps1": case.ps1,
           "as_of": case.as_of.isoformat(), "master_patch": case.master_patch, "xfail": case.xfail, "steps": steps}
    (out / "case.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return doc


def build_all(root: Path) -> list[dict]:
    if len({c.id for c in CASES}) != len(CASES):
        raise ValueError("duplicate case ids in the catalogue")
    if root.exists():
        for child in root.iterdir():  # cases removed from the catalogue must not linger
            if child.is_dir() and child.name not in {c.id for c in CASES}:
                shutil.rmtree(child)
    return [build_case(c, root / c.id) for c in CASES]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=CASES_DIR)
    args = ap.parse_args()
    docs = build_all(args.out)
    print(f"wrote {len(docs)} cases to {args.out}")


if __name__ == "__main__":
    main()
