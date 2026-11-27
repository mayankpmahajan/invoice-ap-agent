"""Every eval case (backend/evals/cases) through the real pipeline with only the model calls stubbed.

One generic runner: the vision stub returns the case's ground-truth extraction, the matcher stub returns the answer
recorded in the case. Priors run first in the same isolated database; every step's outcome is asserted.
"""

import asyncio
import filecmp
from pathlib import Path

import pytest

from app import settings
from evals.dataset import check_quotes, page_texts
from evals.runner import CASES_DIR, compare, load_cases, run_case

CASES = load_cases()


def _param(case: dict):
    marks = [pytest.mark.xfail(reason=case["xfail"], strict=True)] if case.get("xfail") else []
    return pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_case_outcome(case, tmp_path):
    results = asyncio.run(run_case(case, CASES_DIR / case["id"], tmp_path))
    problems = [f"{step['file']}: {p}" for step, res in zip(case["steps"], results)
                for p in compare(step["expected"], res)]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"]) for c in CASES])
def test_ground_truth_quotes_are_in_the_pdf_text(case):
    """For every page that has a text layer, each ground-truth quote is printed there verbatim."""
    for step in case["steps"]:
        if step["extraction"] is None or step["pdf_kind"] == "scanned":
            continue
        texts = page_texts((CASES_DIR / case["id"] / step["file"]).read_bytes())
        on_scanned_pages = [name for name, val in step["extraction"].items() if isinstance(val, dict)
                            and val.get("page") and len(texts[val["page"] - 1].strip()) < settings.TEXT_LAYER_MIN_CHARS_PER_PAGE]
        problems = check_quotes(step["extraction"], texts, step["image_only_fields"] + on_scanned_pages)
        assert not problems, f"{step['file']}: {problems}"


def test_dataset_is_what_the_generator_builds(tmp_path):
    """The committed PDFs and case.json files are exactly what evals/build_cases.py produces from the catalogue."""
    from evals.build_cases import build_all

    build_all(tmp_path)
    built = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    committed = sorted(p.relative_to(CASES_DIR) for p in CASES_DIR.rglob("*") if p.is_file())
    assert built == committed, "case files differ: run `uv run python -m evals.build_cases`"
    stale = [str(p) for p in built if not filecmp.cmp(tmp_path / p, CASES_DIR / p, shallow=False)]
    assert not stale, f"out of date, rebuild with `uv run python -m evals.build_cases`: {stale}"


# Every (check, outcome) branch in app/rules.py that a case can reach, plus the pipeline's own paths.
RULE_BRANCHES = {
    ("document_type", "reject"), ("document_type", "review"), ("required_fields", "review"),
    ("grounding", "review"), ("grounding", "info"), ("arithmetic", "review"), ("vendor", "reject"),
    ("tax_id", "review"), ("bank_details", "info"), ("bank_details", "review"), ("duplicate", "reject"),
    ("duplicate", "review"), ("po_match", "review"), ("po_match", "info"), ("currency", "review"),
    ("price_variance", "info"), ("price_variance", "review"), ("line_detail", "review"),
    ("line_mapping", "review"), ("po_balance", "review"), ("dates", "review"),
}


def test_catalogue_reaches_every_rule_branch():
    subjects = [c["steps"][-1]["expected"] for c in CASES if not c.get("xfail")]
    reached = {(k, v) for e in subjects for k, v in e["checks"].items()}
    assert RULE_BRANCHES <= reached, f"no passing case reaches: {sorted(RULE_BRANCHES - reached)}"
    assert {e["decision"] for e in subjects} >= {"approved", "needs_review", "rejected"}
    assert {e["how"] for e in subjects} >= {"exact identifiers", "model", "skipped"}
    assert {e["settled_by"] for e in subjects} >= {"generator", "critique"}
    assert "failed" in {e["status"] for e in subjects}
    assert {s["review"] for c in CASES for s in c["steps"]} >= {"approved", "rejected"}
    assert {s["pdf_kind"] for c in CASES for s in c["steps"]} >= {"digital", "scanned", "mixed", "broken"}
