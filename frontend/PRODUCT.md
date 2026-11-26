# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: an accounts-payable reviewer (AP clerk or controller) at a mid-size company who works the invoice queue daily: scans what came in, triages invoices the agent held, approves or rejects them, and needs to trust why each decision was made.
Secondary: interviewers at an AI-ops-for-finance company evaluating the build in a live demo, and a non-technical finance buyer watching it run.

## Product Purpose
AP Agent takes a vendor invoice PDF (digital or scanned) and returns approved / needs review / rejected with every reason visible. Success: routine invoices clear without a person, risky ones (over-billing, duplicates, bank-detail changes, unknown vendors) are stopped with a plain explanation, and a reviewer can settle a held invoice in seconds.

## Positioning
The model reads; deterministic rules decide. Every extracted value carries a confidence level and a verbatim quote checked against the PDF's own text, and every decision is a list of named checks with evidence and a full audit trail (models, prompt versions, file hash). Explainability is the product, not a feature.

## Operating Context
Invoices arrive as PDFs (upload or demo samples). Each run streams stage by stage: read PDF, extract fields, verify, match vendor and PO, duplicate check, compare against PO, decision. Reviewers act on held invoices (approve / reject with a note). Procurement master data: vendors (with bank accounts on file, approved or blocked) and purchase orders with lines and invoiced balance.

## Capabilities and Constraints
- React 19 + Vite + Tailwind 4 frontend served by a FastAPI backend; live updates over SSE; types generated from OpenAPI.
- Six demo invoices: happy path, split PO pair (second over-bills), scanned with no PO, disguised duplicate, bank-details change.
- Must not use Zamp or Pace branding (case-study rule).
- Demo runs live in an interview; must stay readable on a shared screen and at laptop widths.

## Brand Commitments
Name: "AP Agent". No other brand assets exist.

## Evidence on Hand
Sample invoices in `../samples/`, seed vendors and POs in `../backend/seed/`. No customers, testimonials or metrics exist; do not fabricate any.

## Product Principles
1. Show the reason before the result: a decision is never shown without the checks behind it.
2. The reviewer's attention is the scarce resource: held and rejected items lead, passes recede.
3. Money and identifiers are exact: amounts, invoice numbers, PO numbers and accounts are shown as printed, never rounded or paraphrased.
4. Provenance is always one step away: page, quote, confidence and model call for any value.
