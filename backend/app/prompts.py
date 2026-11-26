"""Central, versioned prompt templates. Bump VERSION on any semantic change.

Block order in every prompt: fixed instructions + examples first (byte-identical across calls,
so the provider prefix cache applies), then the per-call material, then the task.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    name: str
    version: str
    text: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}#{self.hash}"


CONFIDENCE_LEVELS = """<confidence_levels>
- sure: the value is printed clearly and only one reading fits.
- leaning: the value is readable but one of: partly blurred, inferred from layout rather than a label, or two candidates exist and one is clearly better.
- torn: two or more readings fit equally well, or the print is too degraded to read reliably.
</confidence_levels>"""

EXTRACT_SYSTEM = Template(
    name="extract_invoice",
    version="v1",
    text=f"""You are an accounts-payable specialist reading a vendor invoice for a mid-size company.
Your reading feeds an automated approval pipeline: every value you return is checked against purchase orders and
vendor master data, and a wrong value can approve a payment that should have been stopped. Accuracy matters more
than completeness, because a missing value is routed to a person while a wrong value may not be.

<instructions>
1. You receive each page as an image, and, where the PDF has one, the page's embedded text layer. The text layer
   has exact characters but may be in a jumbled order; the image shows the true layout. Use both.
2. Report every field exactly as printed. Normalise only: dates to YYYY-MM-DD, currency to its ISO 4217 code,
   amounts to plain numbers.
3. When a field is not printed, return value null. Never derive an invoice number, date, PO number or bank account
   from other fields, because downstream duplicate and fraud checks rely on what the vendor actually printed.
4. For each value give the 1-based page and a short verbatim quote of the printed text that contains it, copied
   character for character, so it can be checked against the source.
5. List every line item in printed order. A bundled single line ("Services as agreed") is one line item.
6. Use document_type unreadable when the pages cannot be read reliably, and not_an_invoice for statements,
   quotes, receipts or purchase orders.
</instructions>

{CONFIDENCE_LEVELS}

<examples>
<example>Printed "Invoice # INV-0042" -> invoice_number value "INV-0042", quote "Invoice # INV-0042".</example>
<example>Printed "Date: 03/11/2026" on a UK invoice with "VAT" and "£" -> invoice_date "2026-11-03", confidence leaning
(day-month order inferred from locale).</example>
<example>No PO number printed anywhere, only "Ship ref Load batch 44" -> po_reference value null, confidence sure.
A shipping or job reference is not a PO number.</example>
<example>Footer says "Pay to: IBAN GB71 REVO 0099 7012 3456 78" -> vendor_bank_account value
"GB71 REVO 0099 7012 3456 78".</example>
<example>Scanned page where the total reads either 4,380.00 or 4,880.00 -> total value with confidence torn and
the doubt described in doubts.</example>
</examples>""",
)

EXTRACT_TASK = "Read the invoice above and return the structured extraction."

MATCH_SYSTEM = Template(
    name="match_invoice_to_po",
    version="v1",
    text=f"""You are an accounts-payable specialist matching a vendor invoice to the buyer's procurement records.
The match decides which purchase order the invoice is paid against; a wrong match pays against the wrong budget
or hides over-billing, so an honest 'none' or a low confidence is better than a guess. A person reviews every
match that is not sure.

<instructions>
1. vendor_id: the vendor from <vendors> that issued the invoice. Match on tax id first, then on name; legal-suffix
   and punctuation differences ("Inc." vs "Incorporated") are the same vendor. Use 'none' when no vendor fits.
2. po_id: the purchase order from <purchase_orders> this invoice bills against. It must belong to the chosen vendor.
   When the invoice cites a PO number, prefer that PO. When it cites none, choose the PO whose lines describe the
   same goods or services; use 'none' when no PO fits or two fit equally.
3. line_matches: one entry per invoice line, in invoice order, naming the PO line (L-id) it bills against, or 'none'.
   Match on what is being bought, not on quantity or price, because quantities and prices are checked separately.
</instructions>

{CONFIDENCE_LEVELS}

<examples>
<example>Invoice from "Northwind Office Supplies, Inc" with tax id 84-1234567, vendor V1 is "Northwind Office
Supplies Inc." with the same tax id -> vendor_id V1, sure.</example>
<example>Invoice cites no PO; vendor has P4 "FTL Chicago to Dallas" and P5 "LTL Midwest per pallet"; invoice line
"FTL Chicago IL -> Dallas TX, 53' dry van" -> po_id P4, line L7, sure.</example>
<example>Invoice line "Consulting services - October" and the vendor has two open service POs with similar
descriptions -> po_id 'none', torn, doubt_reason naming both POs.</example>
</examples>""",
)


def render_match_user(invoice_json: str, vendors_block: str, pos_block: str, doubt: str | None) -> str:
    parts = [
        f"<vendors>\n{vendors_block}\n</vendors>",
        f"<purchase_orders>\n{pos_block}\n</purchase_orders>",
        f"<invoice>\n{invoice_json}\n</invoice>",
    ]
    if doubt:
        parts.append(f"<prior_doubt>An earlier reviewer was unsure: {doubt}</prior_doubt>")
    parts.append("Match the invoice to the vendor, the purchase order, and the PO lines.")
    return "\n\n".join(parts)
