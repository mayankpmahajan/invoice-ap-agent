"""Deterministic AP checks and the decision. No I/O and no model calls: the model reads, these rules decide.

Every check returns pass / info / review / reject with a plain-language detail and its evidence.
Decision: any reject -> rejected; else any review -> needs_review; else approved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app import settings
from app.schemas import InvoiceExtraction

Outcome = Literal["pass", "info", "review", "reject"]


@dataclass
class Check:
    id: str
    title: str
    outcome: Outcome
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class VendorRec:
    vendor_id: str
    name: str
    tax_id: str
    bank_account: str
    status: str
    currency: str


@dataclass
class POLineRec:
    id: str  # "<po_number>#<line_no>"
    sku: str | None
    description: str
    quantity: float
    unit_price: float


@dataclass
class PORec:
    po_number: str
    vendor_id: str
    currency: str
    status: str
    lines: list[POLineRec]

    @property
    def total(self) -> float:
        return round(sum(l.quantity * l.unit_price for l in self.lines), 2)


@dataclass
class LedgerRec:
    run_id: str
    vendor_id: str | None
    invoice_number: str | None
    invoice_number_norm: str | None
    invoice_date: date | None
    total: float | None
    net_amount: float | None
    po_number: str | None
    file_hash: str
    status: str
    po_line_quantities: dict[str, float]


# ------------------------------------------------------------------ helpers
def norm_invoice_number(s: str | None) -> str | None:
    """INV-0042, inv 42, INV#042 -> INV42: case, punctuation and leading zeros are formatting, not identity."""
    if not s:
        return None
    alnum = re.sub(r"[^A-Z0-9]", "", s.upper())
    return re.sub(r"\d+", lambda m: str(int(m.group())), alnum) or None


def norm_account(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def within_tolerance(actual: float, expected: float) -> bool:
    diff = abs(actual - expected)
    if diff <= settings.TOLERANCE_ABS:
        return True
    return expected != 0 and diff / abs(expected) * 100 <= settings.TOLERANCE_PCT


def parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def net_amount(ex: InvoiceExtraction) -> float | None:
    """Pre-tax amount billed (POs are pre-tax)."""
    if ex.subtotal.value is not None:
        return ex.subtotal.value
    if ex.total.value is not None:
        return round(ex.total.value - (ex.tax_amount.value or 0), 2)
    return None


# ------------------------------------------------------------------ checks: the document itself
def check_document_type(ex: InvoiceExtraction) -> Check:
    t = ex.document_type
    if t == "invoice":
        return Check("document_type", "Document is an invoice", "pass", "The document reads as a vendor invoice.")
    if t == "not_an_invoice":
        return Check("document_type", "Document is an invoice", "reject",
                     "The document is not an invoice (e.g. a quote, statement or PO); nothing to pay.")
    if t == "credit_note":
        return Check("document_type", "Document is an invoice", "review",
                     "This is a credit note; it must be applied against an existing invoice by AP.")
    return Check("document_type", "Document is an invoice", "review", "The pages could not be read reliably.")


def check_required_fields(ex: InvoiceExtraction) -> Check:
    missing = [f for f in settings.CRITICAL_FIELDS if getattr(ex, f).value is None]
    if not missing:
        return Check("required_fields", "Required fields present", "pass", "Vendor, number, date, currency and total are all printed.")
    return Check("required_fields", "Required fields present", "review",
                 f"Missing on the invoice: {', '.join(missing)}. Ask the vendor for a corrected invoice.",
                 {"missing": missing})


def check_grounding(ex: InvoiceExtraction, verified: dict[str, bool], has_text_layer: bool) -> Check:
    """verified: field -> quote found verbatim in the PDF's own text layer (only meaningful for digital PDFs)."""
    critical = [f for f in settings.CRITICAL_FIELDS if getattr(ex, f).value is not None]
    if has_text_layer:
        failed = [f for f in critical if not verified.get(f)]
        if failed:
            return Check("grounding", "Values match the PDF's own text", "review",
                         f"Could not find these values in the PDF's embedded text: {', '.join(failed)}.",
                         {"unverified": failed, "verified": verified})
        return Check("grounding", "Values match the PDF's own text", "pass",
                     "Every key value was found verbatim in the PDF's embedded text.", {"verified": verified})
    unsure = [f for f in critical if getattr(ex, f).confidence != "sure"]
    if unsure:
        return Check("grounding", "Scanned invoice read with confidence", "review",
                     f"Scanned invoice (no text to cross-check) and the reader was unsure of: {', '.join(unsure)}.",
                     {"unsure": unsure})
    return Check("grounding", "Scanned invoice read with confidence", "info",
                 "Scanned invoice with no embedded text; the reader was sure of every key value.")


def check_arithmetic(ex: InvoiceExtraction) -> Check:
    slack = settings.ARITHMETIC_SLACK
    problems: list[str] = []
    for i, li in enumerate(ex.line_items, 1):
        if None not in (li.quantity, li.unit_price, li.amount) and abs(li.quantity * li.unit_price - li.amount) > slack:
            problems.append(f"line {i}: {li.quantity} x {li.unit_price} != {li.amount}")
    line_sum = round(sum(li.amount or 0 for li in ex.line_items), 2)
    sub, tax, tot = ex.subtotal.value, ex.tax_amount.value, ex.total.value
    target = tot if ex.amounts_include_tax else sub
    if target is not None and ex.line_items and abs(line_sum - target) > slack * max(1, len(ex.line_items)):
        problems.append(f"lines add up to {line_sum}, invoice shows {target}")
    if not ex.amounts_include_tax and None not in (sub, tot) and abs(sub + (tax or 0) - tot) > slack:
        problems.append(f"subtotal {sub} + tax {tax or 0} != total {tot}")
    if problems:
        return Check("arithmetic", "Invoice arithmetic adds up", "review", "; ".join(problems), {"line_sum": line_sum})
    return Check("arithmetic", "Invoice arithmetic adds up", "pass",
                 f"Lines sum to {line_sum}; subtotal, tax and total are consistent.", {"line_sum": line_sum})


# ------------------------------------------------------------------ checks: vendor
def check_vendor(vendor: VendorRec | None, ex: InvoiceExtraction) -> Check:
    if vendor is None:
        return Check("vendor", "Vendor is approved", "reject",
                     f"'{ex.vendor_name.value}' is not in the vendor master. The vendor must be onboarded before payment.")
    if vendor.status != "approved":
        return Check("vendor", "Vendor is approved", "reject",
                     f"{vendor.name} is {vendor.status} in the vendor master; invoices cannot be paid.",
                     {"vendor_id": vendor.vendor_id})
    return Check("vendor", "Vendor is approved", "pass", f"Matched {vendor.name} ({vendor.vendor_id}), approved.",
                 {"vendor_id": vendor.vendor_id})


def check_bank_details(vendor: VendorRec | None, ex: InvoiceExtraction) -> Check:
    if vendor is None:
        return Check("bank_details", "Bank details match vendor record", "info", "No vendor record to compare against.")
    printed = norm_account(ex.vendor_bank_account.value)
    if not printed:
        return Check("bank_details", "Bank details match vendor record", "info",
                     "No bank details printed; payment goes to the account on file.")
    on_file = norm_account(vendor.bank_account)
    if printed == on_file or printed.endswith(on_file[-8:]) or on_file.endswith(printed[-8:]):
        return Check("bank_details", "Bank details match vendor record", "pass", "Printed bank account matches the account on file.")
    return Check("bank_details", "Bank details match vendor record", "review",
                 "The invoice asks for payment to a different bank account than the one on file. This is the most "
                 "common invoice-fraud pattern: verify the change with the vendor through a known contact before paying.",
                 {"printed": ex.vendor_bank_account.value, "on_file": vendor.bank_account})


# ------------------------------------------------------------------ checks: duplicates
def check_duplicate(ex: InvoiceExtraction, vendor_id: str | None, file_hash: str, ledger: list[LedgerRec]) -> Check:
    live = [r for r in ledger if r.status != "rejected"]
    for r in live:
        if r.file_hash == file_hash:
            return Check("duplicate", "Not a duplicate", "reject", "This exact file was already processed.",
                         {"original_run": r.run_id, "match": "file"})
    num = norm_invoice_number(ex.invoice_number.value)
    for r in live:
        if num and vendor_id and r.vendor_id == vendor_id and r.invoice_number_norm == num:
            return Check("duplicate", "Not a duplicate", "reject",
                         f"Invoice {ex.invoice_number.value} from this vendor was already processed as "
                         f"{r.invoice_number} (same number once formatting is ignored).",
                         {"original_run": r.run_id, "match": "vendor+number"})
    inv_date, total = parse_date(ex.invoice_date.value), ex.total.value
    for r in live:
        if (vendor_id and r.vendor_id == vendor_id and total is not None and r.total is not None
                and abs(r.total - total) <= settings.ARITHMETIC_SLACK and inv_date and r.invoice_date
                and abs((inv_date - r.invoice_date).days) <= settings.NEAR_DUPLICATE_WINDOW_DAYS):
            return Check("duplicate", "Not a duplicate", "review",
                         f"Same vendor and same total as invoice {r.invoice_number} within "
                         f"{settings.NEAR_DUPLICATE_WINDOW_DAYS} days, under a different number. Possible re-billing.",
                         {"original_run": r.run_id, "match": "vendor+total+date"})
    return Check("duplicate", "Not a duplicate", "pass", "No earlier invoice with this file, number, or amount pattern.")


# ------------------------------------------------------------------ checks: PO
def check_po(po: PORec | None, vendor_id: str | None, ex: InvoiceExtraction, how: str,
             confidence: str | None, doubt: str | None) -> Check:
    if po is None:
        cited = ex.po_reference.value
        detail = (f"Invoice cites PO {cited}, which does not exist or is not this vendor's." if cited
                  else "Invoice cites no PO and no open PO of this vendor clearly matches it.")
        return Check("po_match", "Matched to an open PO", "review", detail + (f" {doubt}" if doubt else ""))
    if po.vendor_id != vendor_id:
        return Check("po_match", "Matched to an open PO", "review", f"{po.po_number} belongs to a different vendor.")
    if po.status != "open":
        return Check("po_match", "Matched to an open PO", "review", f"{po.po_number} is {po.status}.")
    if how == "inferred" and confidence != "sure":
        return Check("po_match", "Matched to an open PO", "review",
                     f"No PO printed; best candidate is {po.po_number} but the match is {confidence}. {doubt or ''}".strip(),
                     {"po_number": po.po_number, "how": how})
    detail = {"cited": f"Invoice cites {po.po_number}; it is open and belongs to this vendor.",
              "inferred": f"No PO printed; matched to {po.po_number} from the vendor and line items (sure)."}[how]
    return Check("po_match", "Matched to an open PO", "info" if how == "inferred" else "pass", detail,
                 {"po_number": po.po_number, "how": how})


def check_currency(po: PORec | None, ex: InvoiceExtraction) -> Check | None:
    if po is None or ex.currency.value is None:
        return None
    if ex.currency.value.upper() == po.currency:
        return Check("currency", "Currency matches PO", "pass", f"Both in {po.currency}.")
    return Check("currency", "Currency matches PO", "review", f"Invoice is in {ex.currency.value}, PO is in {po.currency}.")


def check_lines_against_po(po: PORec | None, ex: InvoiceExtraction, line_map: list[str | None],
                           ledger: list[LedgerRec]) -> list[Check]:
    """Price variance per line, then quantity and amount still available on the PO (split invoices)."""
    if po is None:
        return []
    by_id = {l.id: l for l in po.lines}
    price_issues, unmapped, qty_issues = [], [], []
    this_qty: dict[str, float] = {}
    for i, (li, lid) in enumerate(zip(ex.line_items, line_map), 1):
        pl = by_id.get(lid or "")
        if pl is None:
            unmapped.append(f"line {i} '{li.description}'")
            continue
        # Tolerance applies to the line's money at stake (qty x price), not to the unit price alone.
        q = li.quantity or 0
        if li.unit_price is not None and not within_tolerance(q * li.unit_price, q * pl.unit_price):
            price_issues.append(f"line {i}: billed {li.unit_price} vs PO {pl.unit_price} "
                                f"({q:g} units, {q * (li.unit_price - pl.unit_price):+,.2f})")
        this_qty[pl.id] = this_qty.get(pl.id, 0) + (li.quantity or 0)

    prior = [r for r in ledger if r.po_number == po.po_number and r.status == "approved"]
    for lid, q in this_qty.items():
        pl = by_id[lid]
        already = sum(r.po_line_quantities.get(lid, 0) for r in prior)
        if already + q > pl.quantity:
            qty_issues.append(f"'{pl.description}': PO allows {pl.quantity:g}, {already:g} already invoiced, "
                              f"this invoice bills {q:g} (over by {already + q - pl.quantity:g})")

    checks = [
        Check("price_variance", "Prices within tolerance", "review" if price_issues else "pass",
              "; ".join(price_issues) if price_issues else
              f"All unit prices within {settings.TOLERANCE_PCT:g}% / {settings.TOLERANCE_ABS:g} of the PO."),
    ]
    if unmapped:
        checks.append(Check("line_mapping", "Every line is on the PO", "review",
                            "Not on the PO: " + "; ".join(unmapped)))
    billed_before = round(sum(r.net_amount or 0 for r in prior), 2)
    net = net_amount(ex) or 0
    remaining = round(po.total - billed_before, 2)
    over_amount = net > remaining and not within_tolerance(net, remaining)
    if qty_issues or over_amount:
        detail = "; ".join(qty_issues) or f"Invoice net {net} exceeds the {remaining} remaining on {po.po_number}."
        checks.append(Check("po_balance", "PO has enough remaining", "review", "Over-billing: " + detail,
                            {"po_total": po.total, "billed_before": billed_before, "this_invoice": net,
                             "remaining_before": remaining, "prior_invoices": [r.invoice_number for r in prior]}))
    else:
        checks.append(Check("po_balance", "PO has enough remaining", "pass",
                            f"{po.po_number}: {billed_before} of {po.total} invoiced before; this invoice ({net}) fits.",
                            {"po_total": po.total, "billed_before": billed_before, "this_invoice": net,
                             "prior_invoices": [r.invoice_number for r in prior]}))
    return checks


# ------------------------------------------------------------------ decision
def decide(checks: list[Check]) -> tuple[str, str]:
    rejects = [c for c in checks if c.outcome == "reject"]
    reviews = [c for c in checks if c.outcome == "review"]
    if rejects:
        return "rejected", " ".join(c.detail for c in rejects)
    if reviews:
        return "needs_review", " ".join(c.detail for c in reviews)
    return "approved", "All checks passed: approved for payment."
