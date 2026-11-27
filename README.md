# Invoice AP Agent (Zamp case study, PS-1)

Takes a vendor invoice PDF and returns **approved / needs review / rejected** with every reason visible, plus a live run view and a dashboard of past runs.

## Run it
```bash
cd backend && echo "OPENROUTER_API_KEY=..." > .env && uv sync
cd ../frontend && npm i && npm run build
cd ../backend && uv run uvicorn app.main:app --port 8077   # UI + API on http://localhost:8077
uv run python scripts/demo_run.py                          # rehearse all demo invoices
uv run pytest -q                                           # rule tests
```
Dev UI with hot reload: `cd frontend && npm run dev` (proxies `/api` to :8077). Regenerate demo PDFs: `uv run python scripts/gen_invoices.py`.

## How it works
`ingest → extract → verify → match → duplicate → po_checks → decision`, each stage streamed live (SSE, replayable after refresh).

- **Extract** - one vision call (Claude Opus 5.5 via OpenRouter) reads page images plus the PDF's own text layer. Every field returns a value, a confidence level (sure / leaning / torn), its page and a verbatim quote.
- **Verify** - digital PDFs: each key value is matched character-for-character against the embedded text. Scans: any key field not "sure" goes to review. Arithmetic is checked in code.
- **Match** - exact tax ID / PO number / SKU first, with no model call. Otherwise one generator call picks vendor, PO and PO line per invoice line. If it is unsure, a different model (GPT-5.6 Sol) answers fresh; if that is still unsure, the invoice is held for a person.
- **Decide** - deterministic rules in `app/rules.py`; the model reads, code decides. Any reject → rejected, any review → needs review, else approved.
- **Audit** - every run stores the model ids, prompt versions + hashes, reasoning effort, tokens, file SHA-256 and code version.

## Edge cases (demo order matters: run 01→06)
| File | Scenario | Expected |
|---|---|---|
| 01 | Clean invoice, explicit PO | Approved |
| 02 → 03 | Split PO: 60 then 50 units on a 100-unit PO | 02 approved, 03 held for over-billing |
| 04 | Scanned image, no PO number | PO inferred from vendor + line items |
| 05 | Re-sent copy of 01 as a scan, number `INV42` vs `INV-0042` | Rejected as duplicate |
| 06 | Amounts match, but bank account changed | Held: likely invoice fraud |

## Assumptions
- POs are pre-tax; tax is compared on the invoice only. Tolerance is ±2% **and** ±50 on each line's money, whichever is tighter (`TOLERANCE_*`): a cheap item billed at ten times its PO price is held even though the difference is under 50.
- Only **approved** invoices use up PO balance; held invoices count once a reviewer approves them.
- Unknown or blocked vendors are rejected (they must be onboarded first). A different bank account is never auto-approved.
- 2-way match (invoice ↔ PO). A goods-receipt 3-way match is the natural next step.
- All tunables live in `backend/app/settings.py`; prompts are versioned in `backend/app/prompts.py`.
