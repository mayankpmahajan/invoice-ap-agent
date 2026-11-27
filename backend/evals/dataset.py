"""Eval dataset model: one invoice spec renders to BOTH the PDF and the ground-truth extraction a perfect reader
would return from it, so the two cannot drift.

Layouts: "classic" reuses scripts/gen_invoices.draw_invoice (the demo look); "modern" is a second, different layout
for what draw_invoice cannot print (custom titles, printed arithmetic errors, missing totals, lump-sum or negative
lines, several pages, a logo instead of a printed name, an appended scanned page). Scans reuse to_scan.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.pdf import normalize_ws
from app.schemas import InvoiceExtraction
from scripts.gen_invoices import ACME, draw_invoice, money, to_scan

ON_FILE = "on_file"  # sentinel: print the vendor's real tax ID / bank details
SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}
FIXED_PDF_DATE = b"(D:20261101000000Z)"


@dataclass(frozen=True)
class VendorProfile:
    name: str
    address: tuple[str, ...]
    tax_label: str
    tax_id: str  # as printed after the label
    email: str
    bank_text: str  # remittance sentence printed in the footer
    bank_value: str  # the account a perfect reader returns from that sentence
    accent: str
    currency: str
    tax_label_default: str
    tax_rate_default: float


VENDORS: dict[str, VendorProfile] = {
    "northwind": VendorProfile(
        "Northwind Office Supplies Inc.", ("1200 Commerce St, Seattle WA 98101",), "EIN", "84-1234567",
        "billing@northwind-supplies.com",
        "Payment terms: Net 30. Remit to JPMorgan Chase, routing 021000021, account 483920117.",
        "routing 021000021, account 483920117", "#1f3a5f", "USD", "Sales tax (8.25%)", 0.0825),
    "meridian": VendorProfile(
        "Meridian Industrial Parts Co.", ("88 Foundry Rd, Cleveland OH 44114",), "Tax ID", "27-5544321",
        "ar@meridian-parts.com", "Remit to Bank of America, ABA 026009593, acct 330188420057. Net 60.",
        "ABA 026009593, acct 330188420057", "#5a2d0c", "USD", "Tax (0% - resale cert. on file)", 0.0),
    "brightline": VendorProfile(
        "Brightline Logistics LLC", ("4100 W 47th St, Chicago IL 60632",), "EIN", "46-7788990",
        "billing@brightline-freight.com", "Wire to Wells Fargo, routing 121000248, account 771203945. Net 45.",
        "routing 121000248, account 771203945", "#0b5d3b", "USD", "Tax", 0.0),
    "cobalt": VendorProfile(
        "Cobalt Cloud Services Ltd", ("21 Finsbury Square, London EC2A 1DX",), "VAT", "GB 293 4471 02",
        "accounts@cobaltcloud.co.uk", "Pay to NatWest, IBAN GB29 NWBK 6016 1331 9268 19, BIC NWBKGB2L.",
        "GB29 NWBK 6016 1331 9268 19", "#3b2a6b", "GBP", "VAT (0% - reverse charge)", 0.0),
    "apex": VendorProfile(
        "Apex Facilities Management", ("600 Lakeside Dr, Columbus OH 43215",), "EIN", "33-1209876",
        "invoices@apexfm.com", "Remit to Citibank, routing 021000089, account 559201774.",
        "routing 021000089, account 559201774", "#7a1f1f", "USD", "Sales tax (7.5%)", 0.075),
    "summit": VendorProfile(  # not in the vendor master
        "Summit Janitorial Services LLC", ("77 Grand Ave, Oakland CA 94612",), "EIN", "91-5550123",
        "ar@summitjanitorial.com", "ACH to U.S. Bank, routing 091000022, account 104477221.",
        "routing 091000022, account 104477221", "#2f4f4f", "USD", "Tax", 0.0),
}


@dataclass
class Line:
    desc: str
    qty: float | None
    price: float | None
    sku: str | None = None
    amount: float | None = None  # printed line total; None = qty x price

    def total(self) -> float:
        if self.amount is not None:
            return self.amount
        return round(self.qty * self.price, 2)


@dataclass
class Doc:
    vendor: str
    lines: list[Line]
    number: str | None = None
    date: str | None = None  # ISO value
    date_text: str | None = None  # as printed; default the ISO value
    due: str | None = None
    due_text: str | None = None
    po: str | None = None
    layout: str = "classic"  # classic | modern
    title: str = "INVOICE"
    doc_type: str = "invoice"
    labels: dict[str, str] = field(default_factory=dict)  # number / date / due / po label overrides
    extra_meta: list[tuple[str, str]] = field(default_factory=list)  # printed, not extracted
    name: str | None = None  # printed vendor name override
    tax_id: str | None = ON_FILE
    bank: tuple[str, str] | str | None = ON_FILE  # (printed sentence, account value) | ON_FILE | None
    currency: str | None = None  # ISO; default the vendor's
    show_currency: bool = True
    tax_rate: float | None = None
    tax_label: str | None = None
    tax_included: bool = False
    subtotal_printed: float | None = None  # overrides for invoices whose own arithmetic is wrong
    tax_printed: float | None = None
    total_printed: float | None = None
    show_total: bool = True
    total_label: str = "Total due"
    show_sku: bool = True
    notes: list[str] = field(default_factory=list)
    page_break: int | None = None  # modern: lines from this index print on page 2
    appendix_scan: bool = False  # modern: a scanned delivery note is appended as an image-only page
    logo_name: bool = False  # modern: the vendor name is only in a logo image
    scan: bool = False
    scan_seed: int = 1
    smudge_total: bool = False  # scan: a stain covers part of the printed total
    unreadable: bool = False  # scan: degraded beyond reading
    confidence: dict[str, str] = field(default_factory=dict)  # field -> confidence a perfect reader would give
    doubts: str = ""
    raw_bytes: bytes | None = None  # a broken file: no rendering, no extraction

    @property
    def profile(self) -> VendorProfile:
        return VENDORS[self.vendor]

    @property
    def iso_currency(self) -> str:
        return self.currency or self.profile.currency


# ------------------------------------------------------------------ what gets printed (shared by layouts + truth)
@dataclass
class Printed:
    name: str
    tax: tuple[str, str] | None  # (printed text, value)
    bank: tuple[str, str] | None
    meta: list[tuple[str, str, str | None, str | None]]  # (label, printed text, field, value)
    rows: list[tuple[Line, list[str], int]]  # (line, printed cells, page)
    totals: list[tuple[str, float, str, str]]  # (label, value, printed money, field)
    symbol: str
    pages: int
    image_only: list[str]  # fields printed only inside an image (no text layer for them)

    def quote(self, label: str, text: str) -> str:
        return f"{label} {text}"


CLASSIC_LABELS = {"number": "Invoice #", "date": "Invoice date", "due": "Due date", "po": "PO number"}
MODERN_LABELS = {"number": "Invoice No:", "date": "Date:", "due": "Due:", "po": "PO Ref:"}


def _money(doc: Doc, v: float, symbol: str) -> str:
    if doc.layout == "classic":
        return money(v, symbol)  # exactly what draw_invoice prints
    return f"-{symbol}{abs(v):,.2f}" if v < 0 else f"{symbol}{v:,.2f}"


def plan(doc: Doc) -> Printed:
    v = doc.profile
    labels = {**(CLASSIC_LABELS if doc.layout == "classic" else MODERN_LABELS), **doc.labels}
    symbol = SYMBOLS[doc.iso_currency] if doc.show_currency else ""
    meta: list[tuple[str, str, str | None, str | None]] = []
    for key, fld, value, text in (("number", "invoice_number", doc.number, doc.number),
                                  ("date", "invoice_date", doc.date, doc.date_text or doc.date),
                                  ("due", "due_date", doc.due, doc.due_text or doc.due),
                                  ("po", "po_reference", doc.po, doc.po)):
        if value is not None:
            meta.append((labels[key], text, fld, value))
    meta += [(k, t, None, None) for k, t in doc.extra_meta]

    pages = 1 if doc.page_break is None else 2
    rows = []
    for i, ln in enumerate(doc.lines):
        cells = [(ln.sku or "") if doc.show_sku else "", ln.desc,
                 "" if ln.qty is None else f"{ln.qty:g}",
                 "" if ln.price is None else _money(doc, ln.price, symbol), _money(doc, ln.total(), symbol)]
        rows.append((ln, cells, 1 if doc.page_break is None or i < doc.page_break else 2))

    line_sum = round(sum(ln.total() for ln in doc.lines), 2)
    rate = doc.tax_rate if doc.tax_rate is not None else v.tax_rate_default
    tax_label = doc.tax_label or v.tax_label_default
    if doc.tax_included:
        total = doc.total_printed if doc.total_printed is not None else line_sum
        tax = doc.tax_printed if doc.tax_printed is not None else round(total - total / (1 + rate), 2)
        sub = doc.subtotal_printed if doc.subtotal_printed is not None else total - tax
        sub_label = "Net amount"
    else:
        sub = doc.subtotal_printed if doc.subtotal_printed is not None else line_sum
        tax = doc.tax_printed if doc.tax_printed is not None else round(sub * rate, 2)
        total = doc.total_printed if doc.total_printed is not None else sub + tax
        sub_label = "Subtotal"
    sub, tax, total = round(sub, 2), round(tax, 2), round(total, 2)
    totals = [(sub_label, sub, "subtotal"), (tax_label, tax, "tax_amount")]
    if doc.show_total:
        totals.append((doc.total_label, total, "total"))
    tax_print = None
    if doc.tax_id is not None:
        tid = v.tax_id if doc.tax_id == ON_FILE else doc.tax_id
        tax_print = (f"{v.tax_label} {tid}", tid)
    bank = (v.bank_text, v.bank_value) if doc.bank == ON_FILE else doc.bank
    return Printed(name=doc.name or v.name, tax=tax_print, bank=bank, meta=meta, rows=rows,
                   totals=[(lbl, val, _money(doc, val, symbol), fld) for lbl, val, fld in totals],
                   symbol=symbol, pages=pages + (1 if doc.appendix_scan else 0),
                   image_only=["vendor_name"] if doc.logo_name else [])


# ------------------------------------------------------------------ ground truth
def ground_truth(doc: Doc) -> dict | None:
    """The extraction a perfect reader returns from the rendered PDF (validated against InvoiceExtraction)."""
    if doc.raw_bytes is not None:
        return None
    conf = doc.confidence.get

    def tf(name: str, value, quote: str | None, page: int | None) -> dict:
        if value is None:
            return {"value": None, "confidence": conf(name, "sure"), "page": None, "quote": None}
        return {"value": value, "confidence": conf(name, "sure"), "page": page, "quote": quote}

    if doc.unreadable:
        empty = {"value": None, "confidence": "torn", "page": None, "quote": None}
        out = {"document_type": "unreadable", "line_items": [], "amounts_include_tax": False, "doubts": doc.doubts,
               **{f: dict(empty) for f in ("vendor_name", "vendor_tax_id", "vendor_bank_account", "invoice_number",
                                           "invoice_date", "due_date", "currency", "po_reference", "subtotal",
                                           "tax_amount", "total")}}
        return InvoiceExtraction.model_validate(out).model_dump(mode="json")

    p = plan(doc)
    last = 1 if doc.page_break is None else 2
    out: dict = {"document_type": doc.doc_type}
    out["vendor_name"] = tf("vendor_name", p.name, p.name, 1)
    out["vendor_tax_id"] = tf("vendor_tax_id", p.tax[1] if p.tax else None, p.tax[0] if p.tax else None, 1)
    out["vendor_bank_account"] = tf("vendor_bank_account", p.bank[1] if p.bank else None,
                                    p.bank[0] if p.bank else None, last)
    by_field = {fld: (lbl, txt, val) for lbl, txt, fld, val in p.meta if fld}
    for fld in ("invoice_number", "invoice_date", "due_date", "po_reference"):
        lbl, txt, val = by_field.get(fld, (None, None, None))
        out[fld] = tf(fld, val, p.quote(lbl, txt) if val is not None else None, 1)
    rows = {fld: (lbl, txt) for lbl, _, txt, fld in p.totals}
    money_row = rows.get("total") or rows.get("subtotal")
    out["currency"] = tf("currency", doc.iso_currency if doc.show_currency else None,
                         p.quote(*money_row) if money_row else None, last)
    for fld in ("subtotal", "tax_amount", "total"):
        val = next((v for _, v, _, f in p.totals if f == fld), None)
        out[fld] = tf(fld, val, p.quote(*rows[fld]) if fld in rows else None, last)
    out["line_items"] = [{
        "description": ln.desc, "sku": ln.sku if doc.show_sku else None, "quantity": ln.qty,
        "unit_price": ln.price, "amount": ln.total(), "page": page,
        "quote": " ".join(c for c in cells if c), "confidence": "sure"} for ln, cells, page in p.rows]
    out["amounts_include_tax"] = doc.tax_included
    out["doubts"] = doc.doubts
    return InvoiceExtraction.model_validate(out).model_dump(mode="json")


def quotes(extraction: dict) -> list[tuple[str, int | None, str]]:
    """(field, page, quote) for every printed value in an extraction."""
    out = []
    for name, val in extraction.items():
        if isinstance(val, dict) and val.get("value") is not None and val.get("quote"):
            out.append((name, val["page"], val["quote"]))
    out += [(f"line_items[{i}]", li["page"], li["quote"]) for i, li in enumerate(extraction["line_items"])]
    return out


def page_texts(pdf: bytes) -> list[str]:
    doc = pdfium.PdfDocument(pdf)
    return [page.get_textpage().get_text_range() for page in doc]


def check_quotes(extraction: dict, texts: list[str], image_only: list[str]) -> list[str]:
    """Every quote must be printed verbatim (whitespace-normalised) in the text layer of its page."""
    problems = []
    for name, page, quote in quotes(extraction):
        if name in image_only:
            continue
        if not page or page > len(texts) or normalize_ws(quote) not in normalize_ws(texts[page - 1]):
            problems.append(f"{name}: quote {quote!r} not on page {page}")
    return problems


# ------------------------------------------------------------------ rendering
def _fix_pdf_dates(path: Path) -> None:
    """Pillow stamps the wall-clock time into a scan's PDF; pin it (same length, so the xref stays valid)."""
    data = re.sub(rb"\(D:\d{14}Z\)", FIXED_PDF_DATE, path.read_bytes())
    path.write_bytes(data)


def _scan(src: Path, dst: Path, seed: int) -> None:
    to_scan(src, dst, seed)  # removes src
    _fix_pdf_dates(dst)


def _rasterise(pdf_path: Path, page: int = 0, scale: float = 2.0) -> Image.Image:
    return pdfium.PdfDocument(str(pdf_path))[page].render(scale=scale).to_pil().convert("RGB")


def _image_pdf(img: Image.Image, dst: Path, pagesize=A4) -> None:
    c = canvas.Canvas(str(dst), pagesize=pagesize, invariant=1)
    c.drawImage(ImageReader(img), 0, 0, *pagesize)
    c.save()


def _text_box(pdf_path: Path, text: str) -> tuple[float, float, float, float]:
    """(left, bottom, right, top) in points of the last occurrence of text on page 1 (text-range indices are
    pdfium char indices, generated line breaks included)."""
    tp = pdfium.PdfDocument(str(pdf_path))[0].get_textpage()
    start = tp.get_text_range().rindex(text)
    boxes = [tp.get_charbox(i) for i in range(start, start + len(text))]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _smudge(pdf_path: Path, text: str, seed: int) -> None:
    """A coffee-ring stain over the middle of `text` (the printed total), baked into an image-only page."""
    scale = 2.0
    left, bottom, right, top = _text_box(pdf_path, text)
    img = _rasterise(pdf_path, scale=scale)
    h_pt = pdfium.PdfDocument(str(pdf_path))[0].get_height()
    cx, cy = (left + right) / 2 * scale, (h_pt - (top + bottom) / 2) * scale
    rx, ry = (right - left) * scale * 0.28, (top - bottom) * scale * 1.1
    stain = Image.new("L", img.size, 0)
    ImageDraw.Draw(stain).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=200)
    stain = stain.filter(ImageFilter.GaussianBlur(3))
    brown = Image.new("RGB", img.size, (92, 64, 40))
    img = Image.composite(brown, img, stain)
    _image_pdf(img, pdf_path)


def _unreadable(pdf_path: Path) -> None:
    """A fax of a fax: almost no resolution left."""
    img = _rasterise(pdf_path, scale=0.22)
    img = img.resize((int(img.width * 7), int(img.height * 7)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(4))
    _image_pdf(img, pdf_path)


def _classic(doc: Doc, p: Printed, dst: Path) -> None:
    bad = [k for k, on in (("subtotal/tax/total overrides", doc.subtotal_printed is not None
                            or doc.tax_printed is not None or doc.total_printed is not None),
                           ("hidden total", not doc.show_total), ("custom title", doc.title != "INVOICE"),
                           ("custom total label", doc.total_label != "Total due"),
                           ("pages", doc.page_break is not None or doc.appendix_scan), ("logo", doc.logo_name),
                           ("notes", bool(doc.notes)), ("no currency", not doc.show_currency),
                           ("lump-sum or explicit line amounts", any(ln.amount is not None or ln.qty is None
                                                                     or ln.price is None for ln in doc.lines)))
           if on]
    if bad:
        raise ValueError(f"classic layout cannot print: {', '.join(bad)} - use layout='modern'")
    v = doc.profile
    tax_line = f"{p.tax[0]}  |  {v.email}" if p.tax else v.email
    footer = ([p.bank[0]] if p.bank else []) + ["Thank you for your business."]
    draw_invoice(dst, vendor={"name": p.name, "address": [*v.address, tax_line]}, bill_to=ACME,
                 meta=[(lbl, txt) for lbl, txt, _, _ in p.meta],
                 lines=[(ln.sku, ln.desc, ln.qty, ln.price) for ln in doc.lines],
                 tax_label=doc.tax_label or v.tax_label_default,
                 tax_rate=doc.tax_rate if doc.tax_rate is not None else v.tax_rate_default,
                 cur=p.symbol, footer=footer, accent=colors.HexColor(v.accent), show_sku=doc.show_sku,
                 tax_included=doc.tax_included)


def _logo(name: str, accent: str, work: Path) -> Image.Image:
    src = work / "_logo.pdf"
    c = canvas.Canvas(str(src), pagesize=(420, 60), invariant=1)
    c.setFillColor(colors.HexColor(accent))
    c.circle(28, 30, 22, fill=1, stroke=0)
    c.setFont("Helvetica-BoldOblique", 22)
    c.drawString(60, 22, name)
    c.save()
    img = _rasterise(src, scale=3)
    src.unlink()
    return img


def _delivery_note(doc: Doc, p: Printed, work: Path, seed: int) -> Image.Image:
    src, scanned = work / "_dn.pdf", work / "_dn_scan.pdf"
    c = canvas.Canvas(str(src), pagesize=A4, invariant=1)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 30 * mm, "DELIVERY NOTE / PROOF OF DELIVERY")
    c.setFont("Helvetica", 10)
    y = h - 45 * mm
    for ln in (p.name, f"Customer PO {doc.po or '-'}", "Delivered to: Acme Manufacturing Corp., Oakland CA",
               *[f"{ln.qty:g} x {ln.desc}" for ln in doc.lines], "", "Goods received in good condition.",
               "Received by: J. Ortega   Signature: ______________"):
        c.drawString(20 * mm, y, ln)
        y -= 7 * mm
    c.save()
    _scan(src, scanned, seed)
    img = _rasterise(scanned, scale=1.0).convert("L")
    scanned.unlink()
    return img


def _modern(doc: Doc, p: Printed, dst: Path, work: Path) -> None:
    v = doc.profile
    size = LETTER if v.currency == "USD" else A4
    w, h = size
    accent = colors.HexColor(v.accent)
    c = canvas.Canvas(str(dst), pagesize=size, invariant=1)
    pages = [doc.lines] if doc.page_break is None else [doc.lines[:doc.page_break], doc.lines[doc.page_break:]]
    rows = iter(p.rows)
    x_desc = 46 * mm if doc.show_sku else 18 * mm

    def table_header(y: float) -> None:
        c.setStrokeColor(accent)
        c.setLineWidth(1)
        c.line(18 * mm, y + 5 * mm, w - 18 * mm, y + 5 * mm)
        c.line(18 * mm, y - 2.5 * mm, w - 18 * mm, y - 2.5 * mm)
        c.setFont("Helvetica-Bold", 8.5)
        if doc.show_sku:
            c.drawString(18 * mm, y, "SKU")
        c.drawString(x_desc, y, "DESCRIPTION")
        c.drawRightString(140 * mm, y, "QTY")
        c.drawRightString(165 * mm, y, "UNIT")
        c.drawRightString(w - 18 * mm, y, "AMOUNT")

    for pi, plines in enumerate(pages):
        last = pi == len(pages) - 1
        c.setFillColor(accent)
        c.rect(0, h - 6 * mm, w, 6 * mm, fill=1, stroke=0)
        c.setFillColor(colors.black)
        if pi == 0:
            if doc.logo_name:
                img = _logo(p.name, v.accent, work)
                c.drawImage(ImageReader(img), 16 * mm, h - 26 * mm, 80 * mm, 80 * mm * img.height / img.width)
            else:
                c.setFont("Helvetica-Bold", 16)
                c.drawString(18 * mm, h - 22 * mm, p.name)
            c.setFont("Helvetica", 8.5)
            info = [*v.address, *([p.tax[0]] if p.tax else []), v.email]
            for i, ln in enumerate(info):
                c.drawString(18 * mm, h - 30 * mm - i * 4 * mm, ln)
            c.setFillColor(accent)
            c.setFont("Helvetica-Bold", 20)
            c.drawRightString(w - 18 * mm, h - 22 * mm, doc.title)
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 9)
            for i, (lbl, txt, _, _) in enumerate(p.meta):
                c.drawRightString(w - 18 * mm, h - 31 * mm - i * 5 * mm, p.quote(lbl, txt))
            y0 = h - 62 * mm
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(18 * mm, y0, "BILL TO")
            c.setFont("Helvetica", 9)
            for i, ln in enumerate(ACME.split("\n")):
                c.drawString(18 * mm, y0 - 5 * mm - i * 4.2 * mm, ln)
            y = h - 95 * mm
        else:
            c.setFont("Helvetica", 8.5)
            c.drawString(18 * mm, h - 16 * mm, f"Continued from page {pi}")
            y = h - 30 * mm
        if plines:
            table_header(y)
            c.setFont("Helvetica", 9)
            for _ in plines:
                _, cells, _ = next(rows)
                y -= 7 * mm
                if doc.show_sku:
                    c.drawString(18 * mm, y, cells[0])
                c.drawString(x_desc, y, cells[1])
                c.drawRightString(140 * mm, y, cells[2])
                c.drawRightString(165 * mm, y, cells[3])
                c.drawRightString(w - 18 * mm, y, cells[4])
            c.setStrokeColor(colors.HexColor("#c9ced6"))
            c.line(18 * mm, y - 3 * mm, w - 18 * mm, y - 3 * mm)
        if last:
            y -= 12 * mm
            c.setFont("Helvetica", 9)
            for i, note in enumerate(doc.notes):
                c.drawString(18 * mm, y - i * 4.5 * mm, note)
            if doc.notes:
                y -= (len(doc.notes) + 1) * 4.5 * mm
            for lbl, _, txt, fld in p.totals:
                bold = fld == "total"
                c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9)
                c.drawString(w - 85 * mm, y, lbl)
                c.drawRightString(w - 18 * mm, y, txt)
                y -= 6 * mm
            c.setFont("Helvetica", 8)
            footer = ([p.bank[0]] if p.bank else []) + ["Questions about this document: " + v.email]
            for i, ln in enumerate(footer):
                c.drawString(18 * mm, 22 * mm - i * 4.2 * mm, ln)
        c.setFont("Helvetica", 7.5)
        c.drawRightString(w - 18 * mm, 10 * mm, f"Page {pi + 1} of {len(pages)}")
        c.showPage()
    if doc.appendix_scan:
        img = _delivery_note(doc, p, work, doc.scan_seed + 100)
        c.drawImage(ImageReader(img), 0, 0, w, h)
        c.showPage()
    c.save()


def render(doc: Doc, dst: Path, work: Path) -> tuple[bytes, list[str]]:
    """Writes the PDF; returns (digital text per page before any scanning, fields printed only as images).
    The pre-scan text lets scanned ground truth be checked against what was printed."""
    if doc.raw_bytes is not None:
        dst.write_bytes(doc.raw_bytes)
        return b"", []
    p = plan(doc)
    src = work / f"_{dst.stem}_src.pdf"
    (_classic(doc, p, src) if doc.layout == "classic" else _modern(doc, p, src, work))
    source = src.read_bytes()
    if doc.scan:
        if doc.smudge_total:
            total_txt = next(txt for _, _, txt, fld in p.totals if fld == "total")
            _smudge(src, total_txt, doc.scan_seed)
        if doc.unreadable:
            _unreadable(src)
        _scan(src, dst, doc.scan_seed)
    else:
        src.replace(dst)
    return source, p.image_only
