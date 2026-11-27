"""The eval case catalogue: every distinct decision path in app/rules.py and app/pipeline.py, and every PS-1
scenario, one case each. Each case is self-contained: prior ledger state is a list of earlier invoices that run
first in the same isolated database (never global order dependence).

Expected outcomes are AP policy as stated in README.md (Assumptions) and the check docstrings, worked out by hand -
not copied from a pipeline run. `checks` lists every check that does NOT pass (info / review / reject); a check
left out must pass. A case whose correct outcome differs from today's code carries `xfail` with the reason.

Fixed seed data: backend/seed/*.csv. PO issue dates: 0412 10-02, 0430 10-20, 0455 09-15, 0461 10-05, 0470 10-28,
0478 09-01 (all 2026). Cases run "as of" AS_OF unless they say otherwise, so date checks never age.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from evals.dataset import Doc, Line

AS_OF = date(2026, 11, 28)
FAST, MODEL, SKIPPED = "exact identifiers", "model", "skipped"


@dataclass
class Match:
    """A recorded matcher answer, in real ids ('none' where the model names nothing)."""
    vendor: str
    po: str
    lines: list[str]
    confidence: str = "sure"
    doubt: str = ""


@dataclass
class Expect:
    decision: str | None
    checks: dict[str, str] = field(default_factory=dict)
    status: str = "completed"
    how: str | None = None  # match path: exact identifiers | model | skipped
    settled_by: str | None = None  # generator | critique (model path only)
    po: str | None = None
    vendor: str | None = None
    po_how: str | None = None  # cited | inferred


@dataclass
class Step:
    doc: Doc
    expect: Expect
    generator: Match | None = None
    critique: Match | None = None
    review: str | None = None  # a person's action on a held invoice after it runs: approved | rejected


@dataclass
class Case:
    id: str
    scenario: str
    branch: str  # the rule / pipeline branch this case exists to exercise
    steps: list[Step]  # priors first, the invoice under test last
    ps1: str = ""  # the PS-1 brief reality it covers, if any
    as_of: date = AS_OF
    master_patch: dict | None = None  # {"purchase_orders": {po: {col: value}}, "vendors": {...}}
    xfail: str | None = None


# ------------------------------------------------------------------ line templates (PO prices from seed)
def chair(q, p=189.00, desc="Ergonomic mesh office chair", **k): return Line(desc, q, p, "NW-CH-220", **k)
def paper(q, p=6.50, desc="A4 copy paper 80gsm (ream)", **k): return Line(desc, q, p, "NW-PP-A4", **k)
def toner(q, p=92.00, desc="HP 58A black toner cartridge", **k): return Line(desc, q, p, "NW-TN-58A", **k)
def coffee(q, p=24.00, desc="Arabica coffee beans 1kg", **k): return Line(desc, q, p, "NW-CF-1KG", **k)
def cups(q, p=4.75, desc="Paper cups 12oz (sleeve of 50)", **k): return Line(desc, q, p, "NW-CU-12", **k)
def seal(q, p=145.00, desc="Hydraulic pump seal kit HP-220", **k): return Line(desc, q, p, "MIP-SK-220", **k)
def ftl(q, p=1850.00, desc="FTL shipment Chicago IL to Dallas TX (53ft dry van)", **k): return Line(desc, q, p, **k)
def ltl(q, p=165.00, desc="LTL shipment Midwest region (per pallet)", **k): return Line(desc, q, p, **k)
def plat(month, p=2400.00): return Line(f"Platform subscription - Enterprise tier ({month})", 1, p, "CCS-PLAT-ENT")
def supp(month, p=350.00): return Line(f"Premium support ({month})", 1, p, "CCS-SUP-PREM")


def nw(lines, **k): return Doc("northwind", lines, **k)
def mer(lines, **k): return Doc("meridian", lines, **k)
def bl(lines, **k): return Doc("brightline", lines, show_sku=False, **k)
def co(lines, **k): return Doc("cobalt", lines, **k)


def one(id, scenario, branch, doc, expect, ps1="", **k) -> Case:
    gen, crit = k.pop("generator", None), k.pop("critique", None)
    return Case(id, scenario, branch, [Step(doc, expect, gen, crit)], ps1=ps1, **k)


NEW_MERIDIAN_BANK = ("Remit to First Horizon Bank, ABA 084000026, acct 9912004471. Net 60. Note: new bank details.",
                     "ABA 084000026, acct 9912004471")
NEW_COBALT_BANK = ("IMPORTANT: our bank details have changed. Pay to Revolut Business, IBAN GB71 REVO 0099 7012 3456 78.",
                   "GB71 REVO 0099 7012 3456 78")
HELD_BANK = Expect("needs_review", {"bank_details": "review"}, how=FAST)

CASES: list[Case] = [
    # ------------------------------------------------------------ the document itself
    one("happy_clean_digital", "Clean text PDF, explicit PO, every line exactly at PO price",
        "every check pass -> approved (fast path: tax ID + PO number + SKUs)",
        nw([chair(40), paper(200), toner(25)], number="INV-0118", date="2026-11-03", due="2026-12-03",
           po="PO-2026-0412"),
        Expect("approved", how=FAST, po="PO-2026-0412", vendor="V-1001", po_how="cited"),
        ps1="clean machine-readable PDF"),
    one("scanned_inferred_po_sure", "Scanned image, no PO printed; generator is sure which PO it is",
        "grounding info (scan, all sure) + po_match info (inferred, sure) -> approved",
        bl([Line("FTL Chicago IL -> Dallas TX, 53' dry van", 3, 1850.00)], number="BL-26-10502",
           date="2026-11-09", date_text="Nov 9, 2026", extra_meta=[("Ship ref", "Load batch 51")],
           scan=True, scan_seed=2),
        Expect("approved", {"grounding": "info", "po_match": "info"}, how=MODEL, settled_by="generator",
               po="PO-2026-0461", po_how="inferred"),
        ps1="scanned image; implied PO",
        generator=Match("V-1002", "PO-2026-0461", ["PO-2026-0461#1"])),
    one("scanned_currency_symbol_only", "Scan showing only a '$' sign: the reader leans USD, the vendor bills in USD",
        "grounding info: an unsure scanned currency confirmed by the exactly-matched vendor's currency",
        nw([coffee(12)], number="INV-0131", date="2026-11-12", date_text="12 Nov 2026", po="PO-2026-0430",
           scan=True, scan_seed=6, confidence={"currency": "leaning"},
           doubts="Only a $ sign is printed; USD assumed."),
        Expect("approved", {"grounding": "info"}, how=FAST, po="PO-2026-0430"),
        ps1="scanned image; currency implied by a symbol"),
    one("scanned_currency_not_vendors", "Scan the reader leans EUR on, from a vendor that bills in USD",
        "grounding review: an unsure currency that master data contradicts stays unsure; currency check vs PO",
        nw([coffee(14)], number="INV-0137", date="2026-11-13", date_text="13 Nov 2026", po="PO-2026-0430",
           scan=True, scan_seed=7, confidence={"currency": "leaning"}, currency="EUR",
           doubts="The currency symbol is smudged; it may be a euro sign."),
        Expect("needs_review", {"grounding": "review", "currency": "review"}, how=FAST, po="PO-2026-0430"),
        ps1="scanned image; unclear currency"),
    one("scanned_smudged_total", "Scan with a stain over the total; the reader cannot be sure of it",
        "grounding review (scanned, a critical field not 'sure')",
        nw([coffee(20), cups(40)], number="INV-0123", date="2026-11-10", date_text="10 Nov 2026",
           po="PO-2026-0430", scan=True, scan_seed=3, smudge_total=True, confidence={"total": "leaning"},
           doubts="A stain covers the middle digits of the total due."),
        Expect("needs_review", {"grounding": "review"}, how=FAST, po="PO-2026-0430"),
        ps1="scanned image; no clear total"),
    one("mixed_digital_with_scanned_appendix", "Digital invoice page plus a scanned signed delivery note page",
        "ingest kind 'mixed' -> grounding takes the scanned path (info when all sure) -> approved",
        mer([seal(30)], number="MIP-7840", date="2026-11-05", po="PO-2026-0455", layout="modern",
            appendix_scan=True, scan_seed=4),
        Expect("approved", {"grounding": "info"}, how=FAST, po="PO-2026-0455")),
    one("multipage_digital", "Two-page digital invoice: lines continue on page 2, totals on page 2, the same PO "
        "line billed on two rows (two deliveries)",
        "per-page text verification; quantities of two rows on one PO line add up to exactly the PO quantity",
        nw([chair(20), paper(100), toner(10), Line("A4 copy paper 80gsm (ream) - second delivery", 100, 6.50,
                                                   "NW-PP-A4")],
           number="NW-INV-0131", date="2026-11-12", date_text="November 12, 2026", po="PO-2026-0412",
           layout="modern", page_break=2),
        Expect("approved", how=FAST, po="PO-2026-0412"),
        ps1="itemised lines"),
    one("vendor_name_only_in_logo", "Digital PDF whose vendor name is only in the letterhead logo image",
        "grounding review (digital, a critical value absent from the text layer)",
        mer([seal(10)], number="MIP-7851", date="2026-11-07", po="PO-2026-0455", layout="modern",
            logo_name=True),
        Expect("needs_review", {"grounding": "review"}, how=FAST, po="PO-2026-0455", vendor="V-1004")),
    one("bundled_line_vat_inclusive", "One bundled line covering two PO lines, VAT inside the price",
        "line_mapping review (bundle maps to no PO line); arithmetic on tax-inclusive lines checks against the total",
        co([Line("Managed cloud services as agreed (platform + support), Oct 2026", 1, 3300.00)],
           number="CCS-INV-2688", date="2026-10-20", date_text="20/10/2026", po="PO-2026-0478",
           labels={"po": "Your PO"}, show_sku=False, tax_included=True, tax_rate=0.20, tax_label="Includes VAT (20%)"),
        Expect("needs_review", {"line_mapping": "review"}, how=MODEL, settled_by="generator", po="PO-2026-0478",
               po_how="cited"),
        ps1="bundled line; tax embedded",
        generator=Match("V-1003", "PO-2026-0478", ["none"])),
    one("tax_inclusive_itemised", "Itemised lines priced VAT-inclusive (20%); net prices equal the PO exactly",
        "price_variance on tax-inclusive lines: the net price must be compared with the pre-tax PO",
        co([plat("Nov 2026", 2880.00), supp("Nov 2026", 420.00)], number="CCS-INV-2695", date="2026-11-02",
           date_text="2 November 2026", po="PO-2026-0478", labels={"po": "Your PO"}, tax_included=True,
           tax_rate=0.20, tax_label="Includes VAT (20%)"),
        Expect("approved", how=FAST, po="PO-2026-0478"),
        ps1="tax embedded in itemised lines"),
    one("missing_invoice_number", "Digital invoice with no invoice number printed",
        "required_fields review (invoice_number); number-based duplicate checks skipped",
        mer([seal(8)], date="2026-11-14", po="PO-2026-0455", layout="modern"),
        Expect("needs_review", {"required_fields": "review"}, how=FAST, po="PO-2026-0455"),
        ps1="missing invoice number"),
    one("missing_invoice_date", "Invoice with no invoice date (and no due date)",
        "required_fields review (invoice_date); dates check not produced; amount+date duplicate check skipped",
        bl([ltl(6)], number="BL-26-10560", po="PO-2026-0470", labels={"po": "PO"}),
        Expect("needs_review", {"required_fields": "review"}, how=FAST, po="PO-2026-0470"),
        ps1="missing date"),
    one("missing_total", "Invoice prints subtotal and tax but no total line",
        "required_fields review (total); PO balance falls back to the subtotal",
        nw([coffee(10), cups(20)], number="INV-0140", date="2026-11-16", po="PO-2026-0430", layout="modern",
           show_total=False),
        Expect("needs_review", {"required_fields": "review"}, how=FAST, po="PO-2026-0430"),
        ps1="no clear total"),
    one("missing_currency", "Amounts printed with no currency symbol or code anywhere",
        "required_fields review (currency); currency check not produced",
        bl([ftl(2)], number="BL-26-10577", date="2026-11-11", po="PO-2026-0461", layout="modern",
           show_currency=False),
        Expect("needs_review", {"required_fields": "review"}, how=FAST, po="PO-2026-0461")),
    one("arithmetic_line_extension_wrong", "A line's qty x unit price does not equal its printed amount",
        "arithmetic review: line qty x price != amount",
        mer([seal(20, amount=2950.00)], number="MIP-7866", date="2026-11-13", po="PO-2026-0455", layout="modern"),
        Expect("needs_review", {"arithmetic": "review"}, how=FAST, po="PO-2026-0455")),
    one("arithmetic_lines_vs_subtotal", "Lines add up to 1,075.00 but the printed subtotal is 1,175.00",
        "arithmetic review: line sum != subtotal",
        nw([chair(5), paper(20)], number="INV-0146", date="2026-11-17", po="PO-2026-0412", layout="modern",
           subtotal_printed=1175.00),
        Expect("needs_review", {"arithmetic": "review"}, how=FAST, po="PO-2026-0412")),
    one("arithmetic_total_wrong", "Subtotal + tax does not equal the printed total (100.00 too high)",
        "arithmetic review: subtotal + tax != total",
        bl([ltl(8)], number="BL-26-10590", date="2026-11-18", po="PO-2026-0470", layout="modern",
           total_printed=1420.00),
        Expect("needs_review", {"arithmetic": "review"}, how=FAST, po="PO-2026-0470")),
    # ------------------------------------------------------------ price tolerance (2% and 50, the tighter wins)
    one("price_inside_tolerance", "Paper at 6.60 vs PO 6.50: +20.00 on 1,300 (1.54%)",
        "price_variance info (inside both bounds) -> approved with the variance noted",
        nw([paper(200, 6.60)], number="INV-0151", date="2026-11-21", date_text="21 Nov 2026", po="PO-2026-0412"),
        Expect("approved", {"price_variance": "info"}, how=FAST, po="PO-2026-0412"),
        ps1="amounts close but not exact; tolerance thresholds"),
    one("price_pct_bound_exceeded", "Cups at 5.00 vs PO 4.75: +20.00 (under 50) but 5.3%",
        "price_variance review via the % bound only",
        nw([cups(80, 5.00)], number="INV-0152", date="2026-11-19", po="PO-2026-0430"),
        Expect("needs_review", {"price_variance": "review"}, how=FAST, po="PO-2026-0430"),
        ps1="tolerance thresholds"),
    one("price_abs_bound_exceeded", "Chairs at 191.50 vs PO 189.00: 1.3% but +100.00 on the line",
        "price_variance review via the absolute bound only",
        nw([chair(40, 191.50)], number="INV-0153", date="2026-11-20", po="PO-2026-0412"),
        Expect("needs_review", {"price_variance": "review"}, how=FAST, po="PO-2026-0412"),
        ps1="tolerance thresholds"),
    one("price_pct_boundary_exact", "Toner at 93.84 vs PO 92.00: exactly +2.00% (+46.00)",
        "price_variance boundary: exactly 2% is inside (info)",
        nw([toner(25, 93.84)], number="INV-0154", date="2026-11-22", po="PO-2026-0412"),
        Expect("approved", {"price_variance": "info"}, how=FAST, po="PO-2026-0412")),
    one("price_abs_boundary_exact", "Chairs at 190.25 vs PO 189.00: exactly +50.00 (0.66%)",
        "price_variance boundary: exactly 50 is inside (info)",
        nw([chair(40, 190.25)], number="INV-0155", date="2026-11-23", po="PO-2026-0412"),
        Expect("approved", {"price_variance": "info"}, how=FAST, po="PO-2026-0412")),
    # ------------------------------------------------------------ split PO / PO balance
    Case("split_po_within_balance", "FTL PO of 12 loads: 8 approved earlier, this invoice bills the last 4",
         "po_balance pass at exactly the PO quantity; fast path matched on description (no SKUs)",
         [Step(bl([ftl(8)], number="BL-26-10401", date="2026-10-20", po="PO-2026-0461"),
               Expect("approved", how=FAST)),
          Step(bl([ftl(4)], number="BL-26-10466", date="2026-11-15", po="PO-2026-0461", layout="modern"),
               Expect("approved", how=FAST, po="PO-2026-0461"))],
         ps1="vendor splits one PO into several invoices"),
    Case("split_po_over_quantity", "Seal-kit PO of 100: 60 approved earlier, this invoice bills 50 more",
         "po_balance review: quantity over the PO line",
         [Step(mer([seal(60)], number="MIP-7901", date="2026-10-10", po="PO-2026-0455"), Expect("approved", how=FAST)),
          Step(mer([seal(50)], number="MIP-7915", date="2026-11-12", po="PO-2026-0455"),
               Expect("needs_review", {"po_balance": "review"}, how=FAST, po="PO-2026-0455"))],
         ps1="vendor splits one PO into several invoices"),
    Case("split_po_prior_held", "60 kits billed earlier but that invoice is still held (bank change); 50 more now",
         "held prior invoices do not consume PO balance -> approved",
         [Step(mer([seal(60)], number="MIP-7920", date="2026-10-14", po="PO-2026-0455", bank=NEW_MERIDIAN_BANK),
               HELD_BANK),
          Step(mer([seal(50)], number="MIP-7934", date="2026-11-16", po="PO-2026-0455"),
               Expect("approved", how=FAST, po="PO-2026-0455"))]),
    Case("split_po_prior_reviewer_approved", "Same held prior, but a reviewer approved it; 50 more now",
         "a reviewer's approval makes the held prior count -> po_balance review",
         [Step(mer([seal(60)], number="MIP-7940", date="2026-10-14", po="PO-2026-0455", bank=NEW_MERIDIAN_BANK),
               HELD_BANK, review="approved"),
          Step(mer([seal(50)], number="MIP-7952", date="2026-11-16", po="PO-2026-0455"),
               Expect("needs_review", {"po_balance": "review"}, how=FAST, po="PO-2026-0455"))]),
    Case("cumulative_price_drift_over_po", "Two invoices each within price tolerance (+39.20, +49.80) that together "
         "bill 89.00 more than the PO total, quantities exactly at the PO",
         "po_balance review via the amount bound (no quantity over-run)",
         [Step(mer([seal(40, 145.98)], number="MIP-7960", date="2026-10-12", po="PO-2026-0455"),
               Expect("approved", {"price_variance": "info"}, how=FAST)),
          Step(mer([seal(60, 145.83)], number="MIP-7973", date="2026-11-18", po="PO-2026-0455"),
               Expect("needs_review", {"price_variance": "info", "po_balance": "review"}, how=FAST,
                      po="PO-2026-0455"))],
         ps1="amounts close but not exact, across a split"),
    # ------------------------------------------------------------ duplicates
    Case("duplicate_exact_file", "The same PDF file sent twice",
         "duplicate reject by file hash; PO comparison skipped",
         [Step(nw([coffee(10)], number="INV-0160", date="2026-11-04", po="PO-2026-0430"), Expect("approved", how=FAST)),
          Step(nw([coffee(10)], number="INV-0160", date="2026-11-04", po="PO-2026-0430"),
               Expect("rejected", {"duplicate": "reject"}, how=FAST, po="PO-2026-0430"))],
         ps1="duplicate detection"),
    Case("duplicate_number_reformatted", "Same invoice re-sent from another system: INV-0162 becomes INV0162",
         "duplicate reject by vendor + normalised number",
         [Step(nw([coffee(12)], number="INV-0162", date="2026-11-06", po="PO-2026-0430"), Expect("approved", how=FAST)),
          Step(nw([coffee(12)], number="INV0162", date="2026-11-06", po="PO-2026-0430", layout="modern"),
               Expect("rejected", {"duplicate": "reject"}, how=FAST, po="PO-2026-0430"))],
         ps1="duplicate detection"),
    Case("duplicate_near_number", "MIP-26-1105 processed; now MIP-2611-05 for a different amount",
         "duplicate review: same characters, different number split",
         [Step(mer([seal(10)], number="MIP-26-1105", date="2026-11-05", po="PO-2026-0455"), Expect("approved", how=FAST)),
          Step(mer([seal(12)], number="MIP-2611-05", date="2026-11-06", po="PO-2026-0455"),
               Expect("needs_review", {"duplicate": "review"}, how=FAST, po="PO-2026-0455"))],
         ps1="duplicate detection"),
    Case("duplicate_amount_and_date", "Same vendor, same total, 5 days apart, new invoice number",
         "duplicate review: vendor + total + date window",
         [Step(bl([ltl(10)], number="BL-26-10612", date="2026-11-02", po="PO-2026-0470"), Expect("approved", how=FAST)),
          Step(bl([ltl(10)], number="BL-26-10637", date="2026-11-07", po="PO-2026-0470"),
               Expect("needs_review", {"duplicate": "review"}, how=FAST, po="PO-2026-0470"))],
         ps1="duplicate detection"),
    Case("duplicate_amount_outside_window", "Same vendor, same total, 31 days apart, new invoice number",
         "duplicate pass just outside the 30-day window",
         [Step(bl([ftl(2)], number="BL-26-10318", date="2026-10-07", po="PO-2026-0461"), Expect("approved", how=FAST)),
          Step(bl([ftl(2)], number="BL-26-10655", date="2026-11-07", po="PO-2026-0461"),
               Expect("approved", how=FAST, po="PO-2026-0461"))]),
    Case("same_number_other_vendor", "Two vendors happen to use invoice number 10045",
         "duplicate pass: number matches are per vendor",
         [Step(nw([coffee(5)], number="10045", date="2026-11-08", po="PO-2026-0430"), Expect("approved", how=FAST)),
          Step(mer([seal(5)], number="10045", date="2026-11-09", po="PO-2026-0455", layout="modern"),
               Expect("approved", how=FAST, po="PO-2026-0455"))]),
    Case("resent_after_rejection", "Original held for a bank change and rejected by a reviewer; vendor re-sends the "
         "same invoice number with the correct bank",
         "rejected ledger entries are ignored by duplicate and balance checks -> approved",
         [Step(co([plat("Nov 2026"), supp("Nov 2026")], number="CCS-INV-2650", date="2026-11-03",
                  po="PO-2026-0478", bank=NEW_COBALT_BANK), HELD_BANK, review="rejected"),
          Step(co([plat("Nov 2026"), supp("Nov 2026")], number="CCS-INV-2650", date="2026-11-03",
                  po="PO-2026-0478"), Expect("approved", how=FAST, po="PO-2026-0478"))]),
    Case("recurring_monthly_subscription", "Monthly subscription: October and November invoices, same total, "
         "30 days apart, each naming its own billing period",
         "near-duplicate (vendor + total + date) on a recurring PO: held on purpose (policy), see README",
         [Step(co([plat("Oct 2026"), supp("Oct 2026")], number="CCS-INV-2611", date="2026-10-02",
                  po="PO-2026-0478", extra_meta=[("Billing period", "Oct 2026")]), Expect("approved", how=FAST)),
          Step(co([plat("Nov 2026"), supp("Nov 2026")], number="CCS-INV-2702", date="2026-11-01",
                  po="PO-2026-0478", extra_meta=[("Billing period", "Nov 2026")]),
               Expect("needs_review", {"duplicate": "review"}, how=FAST, po="PO-2026-0478"))],
         ps1="duplicate detection rules"),
    # ------------------------------------------------------------ vendor
    one("bank_account_changed", "Amounts match the PO but the remittance account is new",
        "bank_details review (most common invoice-fraud pattern)",
        mer([seal(15)], number="MIP-7988", date="2026-11-10", po="PO-2026-0455", bank=NEW_MERIDIAN_BANK),
        Expect("needs_review", {"bank_details": "review"}, how=FAST, po="PO-2026-0455"),
        ps1="approved vendors"),
    one("no_remittance_or_tax_id", "Minimal invoice: no bank details and no tax ID printed",
        "bank_details info (pays the account on file); tax_id check not produced; vendor found by name",
        bl([ltl(5)], number="BL-26-10671", date="2026-11-12", po="PO-2026-0470", tax_id=None, bank=None),
        Expect("approved", {"bank_details": "info"}, how=FAST, po="PO-2026-0470", vendor="V-1002")),
    one("tax_id_mismatch", "Vendor name matches Northwind but the printed EIN has two digits transposed",
        "tax_id review; vendor matched on name only",
        nw([coffee(6)], number="INV-0171", date="2026-11-13", po="PO-2026-0430", tax_id="84-1234576"),
        Expect("needs_review", {"tax_id": "review"}, how=FAST, po="PO-2026-0430", vendor="V-1001"),
        ps1="approved vendors"),
    one("vendor_trading_name", "Invoice under the trading name 'Northwind Supplies' with the registered EIN",
        "fast match by tax ID when the name differs -> approved",
        nw([toner(5)], number="INV-0172", date="2026-11-14", po="PO-2026-0412", name="Northwind Supplies"),
        Expect("approved", how=FAST, po="PO-2026-0412", vendor="V-1001"),
        ps1="approved vendors"),
    one("vendor_unknown", "Vendor not in the vendor master, no PO",
        "vendor reject (not onboarded); bank info (no record); po_match review",
        Doc("summit", [Line("Office deep clean - October (monthly contract)", 1, 2400.00)], number="SJS-1043",
            date="2026-11-10", layout="modern", show_sku=False),
        Expect("rejected", {"vendor": "reject", "bank_details": "info", "po_match": "review"}, how=MODEL,
               settled_by="generator"),
        ps1="approved vendors",
        generator=Match("none", "none", ["none"])),
    one("vendor_blocked", "Vendor is in the master but blocked",
        "vendor reject (blocked)",
        Doc("apex", [Line("Facility maintenance - November 2026", 1, 3150.00)], number="APX-5512",
            date="2026-11-08", show_sku=False),
        Expect("rejected", {"vendor": "reject", "po_match": "review"}, how=MODEL, settled_by="generator",
               vendor="V-1005"),
        ps1="approved vendors",
        generator=Match("V-1005", "none", ["none"])),
    # ------------------------------------------------------------ document type
    one("credit_note", "A credit note for 2 returned chairs, citing the PO and the original invoice",
        "document_type review (credit note must be applied by AP)",
        nw([chair(2)], number="CN-0019", date="2026-11-20", po="PO-2026-0412", layout="modern",
           title="CREDIT NOTE", doc_type="credit_note", labels={"number": "Credit note No:"},
           extra_meta=[("Original invoice:", "INV-0118")], total_label="Total credit"),
        Expect("needs_review", {"document_type": "review"}, how=FAST, po="PO-2026-0412")),
    one("not_an_invoice_quotation", "A freight quotation sent to the AP inbox",
        "document_type reject; pipeline stops after verify (match skipped)",
        bl([ftl(6)], date="2026-11-21", layout="modern", title="QUOTATION", doc_type="not_an_invoice",
           extra_meta=[("Quote No:", "Q-5531"), ("Valid until:", "2026-12-21")], total_label="Quote total"),
        Expect("rejected", {"document_type": "reject", "required_fields": "review"}, how=SKIPPED)),
    one("unreadable_scan", "A fax-quality scan nobody can read",
        "document_type review (unreadable)",
        nw([coffee(10)], number="INV-0199", date="2026-11-20", po="PO-2026-0430", scan=True, scan_seed=42,
           unreadable=True, doubts="The page is too degraded to read any value."),
        Expect("needs_review", {"document_type": "review", "required_fields": "review", "grounding": "info"},
               how=SKIPPED),
        generator=Match("none", "none", [], "torn", "Nothing on the document is legible."),
        critique=Match("none", "none", [], "torn", "Nothing on the document is legible.")),
    one("corrupt_pdf", "A truncated file that starts like a PDF but cannot be opened",
        "ingest raises -> run status failed (terminal, error stored)",
        Doc("northwind", [], raw_bytes=b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R"),
        Expect(None, status="failed")),
    # ------------------------------------------------------------ dates
    one("date_in_future", "Invoice dated 14 days ahead",
        "dates review: future beyond the 2-day grace",
        mer([seal(6)], number="MIP-8002", date="2026-12-12", date_text="December 12, 2026", po="PO-2026-0455"),
        Expect("needs_review", {"dates": "review"}, how=FAST, po="PO-2026-0455")),
    one("date_future_within_grace", "Invoice dated 2 days ahead (time zones / early issue)",
        "dates pass at the edge of the grace period",
        mer([seal(7)], number="MIP-8010", date="2026-11-30", date_text="Nov 30, 2026", po="PO-2026-0455"),
        Expect("approved", how=FAST, po="PO-2026-0455")),
    one("date_before_po", "Invoice dated before its PO was issued",
        "dates review: before the PO issue date",
        nw([coffee(8)], number="INV-0175", date="2026-10-15", date_text="10/15/2026", po="PO-2026-0430"),
        Expect("needs_review", {"dates": "review"}, how=FAST, po="PO-2026-0430")),
    one("date_stale", "Invoice processed more than a year after its date",
        "dates review: older than 365 days",
        nw([toner(4)], number="INV-0177", date="2026-11-20", po="PO-2026-0412"),
        Expect("needs_review", {"dates": "review"}, how=FAST, po="PO-2026-0412"),
        as_of=date(2027, 12, 1)),
    # ------------------------------------------------------------ PO matching
    one("po_cited_lines_need_model", "PO cited, but lines are described in the vendor's own words with no SKUs",
        "fast path incomplete -> generator maps lines (sure); po_match pass as cited",
        nw([Line("Coffee beans, Arabica, 1 kg bag", 15, 24.00), Line("12 oz paper cups, sleeve of 50", 30, 4.75)],
           number="INV-0180", date="2026-11-15", po="PO-2026-0430", layout="modern", show_sku=False),
        Expect("approved", how=MODEL, settled_by="generator", po="PO-2026-0430", po_how="cited"),
        ps1="matching an invoice to a PO isn't always obvious",
        generator=Match("V-1001", "PO-2026-0430", ["PO-2026-0430#1", "PO-2026-0430#2"])),
    one("po_inferred_by_critique", "No PO printed; the generator is unsure between two POs, the critique is sure",
        "confidence-gated critique settles the match -> po_match info",
        bl([Line("Pallet freight, Midwest LTL", 9, 165.00)], number="BL-26-10688", date="2026-11-16",
           layout="modern"),
        Expect("approved", {"po_match": "info"}, how=MODEL, settled_by="critique", po="PO-2026-0470",
               po_how="inferred"),
        ps1="implied PO",
        generator=Match("V-1002", "PO-2026-0470", ["PO-2026-0470#1"], "leaning",
                        "Two open Brightline POs; the line reads like LTL but does not say per pallet."),
        critique=Match("V-1002", "PO-2026-0470", ["PO-2026-0470#1"])),
    one("po_inferred_unsure", "No PO printed; the line could be FTL or LTL and neither model is sure",
        "po_match review: inferred and not sure after the critique",
        bl([Line("Freight services, Chicago area", 2, 1850.00)], number="BL-26-10694", date="2026-11-17",
           layout="modern"),
        Expect("needs_review", {"po_match": "review"}, how=MODEL, settled_by="critique", po="PO-2026-0461",
               po_how="inferred"),
        ps1="implied PO",
        generator=Match("V-1002", "PO-2026-0461", ["PO-2026-0461#1"], "torn",
                        "Could be FTL (PO-2026-0461) or LTL (PO-2026-0470)."),
        critique=Match("V-1002", "PO-2026-0461", ["PO-2026-0461#1"], "leaning",
                       "The price matches FTL but the description names no lane.")),
    one("po_cited_not_found", "Invoice cites PO-2026-0999, which does not exist",
        "po_match review: cited PO not on file",
        nw([coffee(10)], number="INV-0184", date="2026-11-18", po="PO-2026-0999"),
        Expect("needs_review", {"po_match": "review"}, how=MODEL, settled_by="critique"),
        generator=Match("V-1001", "none", ["none"], "torn",
                        "Cited PO-2026-0999 is not on file; the coffee line resembles PO-2026-0430."),
        critique=Match("V-1001", "none", ["none"], "torn", "The cited PO does not exist.")),
    one("po_none_fits", "No PO printed and the charge (driver detention) is on no open PO",
        "po_match review: no PO cited and none matches",
        bl([Line("Detention - driver wait time (hours)", 4, 85.00)], number="BL-26-10702", date="2026-11-19",
           layout="modern"),
        Expect("needs_review", {"po_match": "review"}, how=MODEL, settled_by="generator"),
        generator=Match("V-1002", "none", ["none"])),
    one("po_belongs_to_other_vendor", "Northwind invoice cites Brightline's PO; the matcher follows the printed PO",
        "po_match review: PO belongs to a different vendor; line_mapping review",
        nw([coffee(10)], number="INV-0188", date="2026-11-20", po="PO-2026-0461"),
        Expect("needs_review", {"po_match": "review", "line_mapping": "review"}, how=MODEL, settled_by="generator",
               po="PO-2026-0461", po_how="cited"),
        generator=Match("V-1001", "PO-2026-0461", ["none"])),
    one("po_closed", "Invoice cites a PO that procurement has closed",
        "po_match review: PO not open",
        nw([coffee(10)], number="INV-0190", date="2026-11-21", po="PO-2026-0430"),
        Expect("needs_review", {"po_match": "review"}, how=FAST, po="PO-2026-0430"),
        master_patch={"purchase_orders": {"PO-2026-0430": {"status": "closed"}}}),
    one("currency_mismatch", "UK vendor bills a GBP PO in US dollars",
        "currency review",
        co([plat("Nov 2026"), supp("Nov 2026")], number="CCS-INV-2720", date="2026-11-04", po="PO-2026-0478",
           currency="USD"),
        Expect("needs_review", {"currency": "review"}, how=FAST, po="PO-2026-0478")),
    # ------------------------------------------------------------ line shapes
    one("negative_return_line", "Invoice nets a returned chair as a negative line against the PO",
        "line_detail review: negative quantity",
        nw([toner(25), chair(-1, desc="Return credit - damaged chair (RMA 5512)")], number="INV-0193",
           date="2026-11-24", po="PO-2026-0412", layout="modern"),
        Expect("needs_review", {"line_detail": "review"}, how=FAST, po="PO-2026-0412")),
    one("zero_quantity_backorder_line", "A backordered line printed with quantity 0 and amount 0.00",
        "zero-quantity line skips the price check and uses no balance -> approved",
        nw([chair(10), paper(50), toner(0, desc="HP 58A black toner cartridge (backordered)")], number="INV-0195",
           date="2026-11-25", po="PO-2026-0412", layout="modern"),
        Expect("approved", how=FAST, po="PO-2026-0412")),
    one("lump_sum_line", "The PO item billed as a lump sum: amount only, no quantity or unit price",
        "line_detail review: no quantity / unit price, so the price cannot be checked",
        mer([seal(None, None, desc="Hydraulic pump seal kit HP-220 - balance of order (lot)", amount=5800.00)],
            number="MIP-8021", date="2026-11-19", po="PO-2026-0455", layout="modern"),
        Expect("needs_review", {"line_detail": "review"}, how=FAST, po="PO-2026-0455"),
        ps1="bundled vs itemised"),
    one("no_line_items", "Summary invoice: a total for a period with no item table",
        "line_detail review: no line items to check against the PO",
        bl([], number="BL-26-10715", date="2026-11-20", po="PO-2026-0461", layout="modern",
           notes=["Charges per load manifest BL-M-2210."], subtotal_printed=5550.00),
        Expect("needs_review", {"line_detail": "review"}, how=FAST, po="PO-2026-0461")),
]
