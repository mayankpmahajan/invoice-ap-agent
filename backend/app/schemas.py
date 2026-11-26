"""Pydantic schemas for LLM structured output.

Models in use reason natively, so no reasoning scratchpad fields. Every field the model
reads off the page carries a confidence level and the verbatim quote it came from, so the
quote can be checked mechanically against the PDF's own text layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["sure", "leaning", "torn"]


class TextField(BaseModel):
    value: str | None = Field(description="The value exactly as printed, or null when the document does not show it.")
    confidence: Confidence
    page: int | None = Field(default=None, ge=1, description="1-based page the value was read from.")
    quote: str | None = Field(default=None, description="Verbatim text from the page that contains the value.")


class AmountField(BaseModel):
    value: float | None = Field(description="Numeric amount without currency symbols or thousands separators, or null.")
    confidence: Confidence
    page: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, description="Verbatim text from the page that contains the amount.")


class LineItem(BaseModel):
    description: str
    sku: str | None = Field(default=None, description="Item / part code if printed, else null.")
    quantity: float | None
    unit_price: float | None
    amount: float | None = Field(description="Line total as printed.")
    page: int = Field(ge=1)
    quote: str = Field(description="Verbatim text of the line row as printed.")
    confidence: Confidence


class InvoiceExtraction(BaseModel):
    document_type: Literal["invoice", "credit_note", "not_an_invoice", "unreadable"]
    vendor_name: TextField
    vendor_tax_id: TextField
    vendor_bank_account: TextField = Field(description="Remittance account / IBAN / routing+account printed for payment.")
    invoice_number: TextField
    invoice_date: TextField = Field(description="value in ISO format YYYY-MM-DD.")
    due_date: TextField = Field(description="value in ISO format YYYY-MM-DD.")
    currency: TextField = Field(description="value as ISO 4217 code, e.g. USD, GBP, EUR.")
    po_reference: TextField = Field(description="Purchase order number the invoice cites, or null when none is printed.")
    line_items: list[LineItem]
    subtotal: AmountField
    tax_amount: AmountField
    total: AmountField
    amounts_include_tax: bool = Field(description="True when line prices are tax-inclusive.")
    doubts: str = Field(description="One or two sentences on anything unclear or missing; empty string when nothing is.")


class MatchDecision(BaseModel):
    """Resolve which vendor, which PO, and which PO line each invoice line bills against."""

    vendor_id: str = Field(description="Short vendor id from the vendor list (e.g. V2), or 'none'.")
    po_id: str = Field(description="Short PO id from the candidate list (e.g. P3), or 'none'.")
    line_matches: list[str] = Field(
        description="One entry per invoice line, in invoice order: the short PO line id it bills against (e.g. L4), or 'none'."
    )
    confidence: Confidence
    doubt_reason: str = Field(description="One sentence on what makes the match unsure; empty string when sure.")
