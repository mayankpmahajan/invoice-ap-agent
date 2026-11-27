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


# Each check is written with the title it carries when it passes. A flagged check must not keep that wording
# ("Not a duplicate" on a duplicate reads as a contradiction), so it is renamed here: pass title -> flagged title,
# or pass title -> {outcome: flagged title} when review and reject need different words.
FLAGGED_TITLES: dict[str, str | dict[str, str]] = {
    "Document is an invoice": {"reject": "Not an invoice", "review": "Document type needs a person"},
    "Required fields present": "Required fields missing",
    "Values match the PDF's own text": "Values not found in the PDF's own text",
    "Scanned invoice read with confidence": "Scanned invoice: reader unsure of key values",
    "Invoice arithmetic adds up": "Invoice arithmetic does not add up",
    "Vendor is approved": "Vendor not approved",
    "Bank details match vendor record": "Bank account differs from vendor record",
    "Not a duplicate": {"reject": "Duplicate invoice", "review": "Possible duplicate"},
    "Matched to an open PO": "No confident PO match",
    "Currency matches PO": "Currency differs from PO",
    "Prices within tolerance": "Prices outside tolerance",
    "Every line is on the PO": "Lines not on the PO",
    "Every line has a quantity and price": "Lines missing quantity or price",
    "Tax ID matches vendor record": "Tax ID differs from vendor record",
    "Invoice date is plausible": "Invoice date needs a person",
    "PO has enough remaining": "Over-billing the PO",
}


@dataclass
class Check:
    id: str
    title: str
    outcome: Outcome
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome in ("review", "reject"):
            flagged = FLAGGED_TITLES.get(self.title)
            if isinstance(flagged, dict):
                flagged = flagged.get(self.outcome)
            if flagged:
                self.title = flagged


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
    issue_date: date | None = None

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
    """INV-0042, inv 42, INV#042 -> INV-42: case, punctuation and leading zeros are formatting, not identity.

    The number is split into runs of letters and runs of digits, so segment boundaries survive: 2026-1-15 and
    2026-11-5 stay different, while INV42 and INV-0042 (same runs) stay equal."""
    if not s:
        return None
    runs = re.findall(r"[A-Z]+|\d+", s.upper())
    return "-".join(str(int(r)) if r.isdigit() else r for r in runs) or None


def collapsed_invoice_number(s: str | None) -> str | None:
    """Every separator and boundary dropped. Equal collapsed numbers with different runs are a near match:
    possibly the same invoice re-typed, possibly two different invoices, so a person decides."""
    if not s:
        return None
    alnum = re.sub(r"[^A-Z0-9]", "", s.upper())
    return re.sub(r"\d+", lambda m: str(int(m.group())), alnum) or None


def norm_account(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def same_tax_id(printed: str | None, on_file: str) -> bool:
    """Labels and formatting differ by country ("EIN 84-1234567", "VAT GB 293 4471 02"), so compare the digits
    when both carry a real number, else the letters and digits."""
    pd, fd = re.sub(r"\D", "", printed or ""), re.sub(r"\D", "", on_file)
    if len(pd) >= 6 and len(fd) >= 6:
        return pd == fd
    return norm_account(printed) == norm_account(on_file)


def within_tolerance(actual: float, expected: float) -> bool:
    """Within BOTH bounds (the lesser of TOLERANCE_PCT and TOLERANCE_ABS). Either-bound let small lines through
    at many times the PO price (a 4.75 item billed at 54 is under 50 absolute) and large lines drift unbounded."""
    diff = abs(actual - expected)
    if diff <= settings.ARITHMETIC_SLACK:  # rounding, not a variance
        return True
    return expected != 0 and diff <= settings.TOLERANCE_ABS and diff / abs(expected) * 100 <= settings.TOLERANCE_PCT


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


def tax_inclusive_net_share(ex: InvoiceExtraction) -> float | None:
    """For tax-inclusive line prices: the share of each price that is net of tax (net / gross), from the invoice's
    own printed tax and total. None when prices exclude tax, or the invoice does not show enough to derive it."""
    if not ex.amounts_include_tax:
        return None
    gross, tax = ex.total.value, ex.tax_amount.value
    if not gross or tax is None or not 0 <= tax < gross:
        return None
    return (gross - tax) / gross


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


def check_grounding(ex: InvoiceExtraction, verified: dict[str, bool], has_text_layer: bool,
                    corroborated: dict[str, str] | None = None) -> Check:
    """verified: field -> quote found verbatim in the PDF's own text layer (only meaningful for digital PDFs).
    corroborated: field -> where an unsure scanned value was confirmed independently (e.g. the currency a "$" sign
    implies, confirmed by the exactly-matched vendor's record). Only scans use it: digital PDFs have the text layer."""
    critical = [f for f in settings.CRITICAL_FIELDS if getattr(ex, f).value is not None]
    corroborated = corroborated or {}
    if has_text_layer:
        failed = [f for f in critical if not verified.get(f)]
        if failed:
            return Check("grounding", "Values match the PDF's own text", "review",
                         f"Could not find these values in the PDF's embedded text: {', '.join(failed)}.",
                         {"unverified": failed, "verified": verified})
        return Check("grounding", "Values match the PDF's own text", "pass",
                     "Every key value was found verbatim in the PDF's embedded text.", {"verified": verified})
    if not critical:
        return Check("grounding", "Scanned invoice read with confidence", "info",
                     "Scanned invoice with no embedded text, and no key value could be read to check.")
    confirmed = {f: corroborated[f] for f in critical if getattr(ex, f).confidence != "sure" and f in corroborated}
    unsure = [f for f in critical if getattr(ex, f).confidence != "sure" and f not in confirmed]
    note = "".join(f" The reader was unsure of {f}, but it matches {src}." for f, src in confirmed.items())
    if unsure:
        return Check("grounding", "Scanned invoice read with confidence", "review",
                     f"Scanned invoice (no text to cross-check) and the reader was unsure of: {', '.join(unsure)}."
                     + note, {"unsure": unsure, "corroborated": confirmed})
    return Check("grounding", "Scanned invoice read with confidence", "info",
                 ("Scanned invoice with no embedded text; the reader was sure of every other key value." if confirmed
                  else "Scanned invoice with no embedded text; the reader was sure of every key value.") + note,
                 {"corroborated": confirmed})


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


def check_dates(ex: InvoiceExtraction, po: PORec | None, today: date) -> Check | None:
    inv = parse_date(ex.invoice_date.value)
    if inv is None:
        return None  # a missing date is already held by required_fields
    problems = []
    if (inv - today).days > settings.INVOICE_FUTURE_GRACE_DAYS:
        problems.append(f"dated {inv.isoformat()}, which is in the future")
    if (today - inv).days > settings.INVOICE_MAX_AGE_DAYS:
        problems.append(f"dated {inv.isoformat()}, more than {settings.INVOICE_MAX_AGE_DAYS} days ago")
    if po is not None and po.issue_date and inv < po.issue_date:
        problems.append(f"dated before {po.po_number} was issued ({po.issue_date.isoformat()})")
    if problems:
        return Check("dates", "Invoice date is plausible", "review", "Invoice is " + "; ".join(problems) + ".",
                     {"invoice_date": inv.isoformat()})
    return Check("dates", "Invoice date is plausible", "pass", f"Dated {inv.isoformat()}.")


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


def check_tax_id(vendor: VendorRec | None, ex: InvoiceExtraction) -> Check | None:
    printed = ex.vendor_tax_id.value
    if vendor is None or not printed:
        return None
    if same_tax_id(printed, vendor.tax_id):
        return Check("tax_id", "Tax ID matches vendor record", "pass", f"Printed tax ID matches {vendor.name}'s record.")
    return Check("tax_id", "Tax ID matches vendor record", "review",
                 f"The invoice prints tax ID {printed}, but {vendor.name}'s record has {vendor.tax_id}. "
                 "Either the vendor was matched on its name only, or the invoice is not from this vendor.",
                 {"printed": printed, "on_file": vendor.tax_id})


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
        if num and vendor_id and r.vendor_id == vendor_id and norm_invoice_number(r.invoice_number) == num:
            return Check("duplicate", "Not a duplicate", "reject",
                         f"Invoice {ex.invoice_number.value} from this vendor was already processed as "
                         f"{r.invoice_number} (same number once formatting is ignored).",
                         {"original_run": r.run_id, "match": "vendor+number"})
    flat = collapsed_invoice_number(ex.invoice_number.value)
    for r in live:
        if flat and vendor_id and r.vendor_id == vendor_id and collapsed_invoice_number(r.invoice_number) == flat:
            return Check("duplicate", "Not a duplicate", "review",
                         f"Invoice {ex.invoice_number.value} looks like {r.invoice_number}, already processed for this "
                         "vendor, but the number is split differently. It may be the same invoice re-typed.",
                         {"original_run": r.run_id, "match": "near-number"})
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
    price_issues, price_notes, unmapped, qty_issues, detail_issues = [], [], [], [], []
    if not ex.line_items:
        detail_issues.append("the invoice has no line items, so nothing can be checked against the PO")
    this_qty: dict[str, float] = {}
    net_share = tax_inclusive_net_share(ex)
    for i, (li, lid) in enumerate(zip(ex.line_items, line_map), 1):
        if li.quantity is None or li.unit_price is None:
            detail_issues.append(f"line {i} '{li.description}' has no {'quantity' if li.quantity is None else 'unit price'}"
                                 " (a bundled or lump-sum line), so its price cannot be checked")
        elif li.quantity < 0 or li.unit_price < 0:
            detail_issues.append(f"line {i} '{li.description}' has a negative quantity or price")
        pl = by_id.get(lid or "")
        if pl is None:
            unmapped.append(f"line {i} '{li.description}'")
            continue
        # Tolerance applies to the line's money at stake (qty x price), not to the unit price alone.
        q = li.quantity or 0
        if li.unit_price is not None and q:
            # POs are pre-tax: a tax-inclusive price is compared net of the invoice's own tax share.
            unit = round(li.unit_price * net_share, 4) if net_share is not None else li.unit_price
            variance = q * (unit - pl.unit_price)
            billed = f"{li.unit_price} incl. tax ({unit:g} net)" if net_share is not None else f"{li.unit_price}"
            note = f"line {i}: billed {billed} vs PO {pl.unit_price} ({q:g} units, {variance:+,.2f})"
            if not within_tolerance(q * unit, q * pl.unit_price):
                price_issues.append(note)
            elif abs(variance) > settings.ARITHMETIC_SLACK:
                price_notes.append(note)
        this_qty[pl.id] = this_qty.get(pl.id, 0) + (li.quantity or 0)

    prior = [r for r in ledger if r.po_number == po.po_number and r.status == "approved"]
    for lid, q in this_qty.items():
        pl = by_id[lid]
        already = sum(r.po_line_quantities.get(lid, 0) for r in prior)
        if already + q > pl.quantity:
            qty_issues.append(f"'{pl.description}': PO allows {pl.quantity:g}, {already:g} already invoiced, "
                              f"this invoice bills {q:g} (over by {already + q - pl.quantity:g})")

    bound = f"{settings.TOLERANCE_PCT:g}% and {settings.TOLERANCE_ABS:g}"
    if price_issues:
        price = Check("price_variance", "Prices within tolerance", "review",
                      f"Beyond the {bound} tolerance: " + "; ".join(price_issues))
    elif price_notes:
        price = Check("price_variance", "Prices within tolerance", "info",
                      f"Close but not exact, inside the {bound} tolerance: " + "; ".join(price_notes))
    else:
        price = Check("price_variance", "Prices within tolerance", "pass", "Every line is billed at the PO price.")
    checks = [price]
    if detail_issues:
        checks.append(Check("line_detail", "Every line has a quantity and price", "review",
                            "; ".join(detail_issues).capitalize() + "."))
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
def decide(checks: list[Check]) -> tuple[str, str, str]:
    """(decision, headline, details). The headline is the one line a buyer reads first: the verdict and the
    reason that decided it; details carry every flagged check."""
    rejects = [c for c in checks if c.outcome == "reject"]
    reviews = [c for c in checks if c.outcome == "review"]
    if rejects or reviews:
        flagged = rejects + reviews
        more = f" (+{len(flagged) - 1} more)" if len(flagged) > 1 else ""
        decision = "rejected" if rejects else "needs_review"
        verb = "Void" if rejects else "Held for a person"
        return decision, f"{verb}: {flagged[0].title}{more}", " ".join(c.detail for c in flagged)
    notes = [c for c in checks if c.outcome == "info"]
    return ("approved", f"Approved: all {len(checks)} checks passed",
            " ".join(c.detail for c in notes) or "Every check passed.")
