"""Generate the demo invoice PDFs (happy path + edge cases) into ../samples/.

Usage: uv run python scripts/gen_invoices.py
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[2] / "samples"
OUT.mkdir(exist_ok=True)


def money(v: float, cur: str = "$") -> str:
    return f"{cur}{v:,.2f}"


def draw_invoice(path: Path, *, vendor: dict, bill_to: str, meta: list[tuple[str, str]],
                 lines: list[tuple], tax_label: str, tax_rate: float, cur: str = "$",
                 footer: list[str] = (), accent=colors.HexColor("#1f3a5f"), show_sku=True) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFillColor(accent)
    c.rect(0, h - 38 * mm, w, 38 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(15 * mm, h - 17 * mm, vendor["name"])
    c.setFont("Helvetica", 9)
    for i, ln in enumerate(vendor["address"]):
        c.drawString(15 * mm, h - 24 * mm - i * 4.2 * mm, ln)
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(w - 15 * mm, h - 20 * mm, "INVOICE")

    c.setFillColor(colors.black)
    y = h - 50 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(15 * mm, y, "Bill to")
    c.setFont("Helvetica", 9)
    for i, ln in enumerate(bill_to.split("\n")):
        c.drawString(15 * mm, y - 5 * mm - i * 4.2 * mm, ln)
    for i, (k, v) in enumerate(meta):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(120 * mm, y - i * 5 * mm, k)
        c.setFont("Helvetica", 9)
        c.drawRightString(w - 15 * mm, y - i * 5 * mm, v)

    y = h - 92 * mm
    cols = [15, 40, 125, 145, 170] if show_sku else [15, 15, 125, 145, 170]
    c.setFillColor(colors.HexColor("#eef2f7"))
    c.rect(13 * mm, y - 2 * mm, w - 26 * mm, 7 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    if show_sku:
        c.drawString(cols[0] * mm, y, "Item")
    c.drawString(cols[1] * mm, y, "Description")
    c.drawRightString((cols[2] + 12) * mm, y, "Qty")
    c.drawRightString((cols[3] + 18) * mm, y, "Unit price")
    c.drawRightString(w - 15 * mm, y, "Amount")
    c.setFont("Helvetica", 9)
    subtotal = 0.0
    for sku, desc, qty, price in lines:
        y -= 7 * mm
        amt = round(qty * price, 2)
        subtotal += amt
        if show_sku:
            c.drawString(cols[0] * mm, y, sku or "")
        c.drawString(cols[1] * mm, y, desc)
        c.drawRightString((cols[2] + 12) * mm, y, f"{qty:g}")
        c.drawRightString((cols[3] + 18) * mm, y, money(price, cur))
        c.drawRightString(w - 15 * mm, y, money(amt, cur))
    tax = round(subtotal * tax_rate, 2)
    y -= 12 * mm
    for k, v, bold in (("Subtotal", subtotal, False), (tax_label, tax, False), ("Total due", subtotal + tax, True)):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9)
        c.drawString(130 * mm, y, k)
        c.drawRightString(w - 15 * mm, y, money(v, cur))
        y -= 6 * mm
    c.setFont("Helvetica", 8)
    for i, ln in enumerate(footer):
        c.drawString(15 * mm, 30 * mm - i * 4.2 * mm, ln)
    c.save()


def to_scan(src: Path, dst: Path, seed: int) -> None:
    """Rasterise to a noisy, slightly rotated image-only PDF (no text layer), like a scanner."""
    rnd = random.Random(seed)
    page = pdfium.PdfDocument(str(src))[0]
    img = page.render(scale=110 / 72).to_pil().convert("L")
    img = img.rotate(rnd.uniform(-1.2, 1.2), expand=True, fillcolor=245)
    px = img.load()
    for _ in range(img.width * img.height // 60):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        px[x, y] = rnd.choice((90, 140, 200))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=110)
    dst.write_bytes(buf.getvalue())
    src.unlink()


ACME = "Acme Manufacturing Corp.\nAccounts Payable\n500 Harbor Blvd, Oakland CA 94607"
NORTHWIND = {"name": "Northwind Office Supplies Inc.",
             "address": ["1200 Commerce St, Seattle WA 98101", "EIN 84-1234567  |  billing@northwind-supplies.com"]}
NW_FOOT = ["Payment terms: Net 30. Remit to JPMorgan Chase, routing 021000021, account 483920117.",
           "Thank you for your business."]
NW_LINES = [("NW-CH-220", "Ergonomic mesh office chair", 40, 189.00),
            ("NW-PP-A4", "A4 copy paper 80gsm (ream)", 200, 6.50),
            ("NW-TN-58A", "HP 58A black toner cartridge", 25, 92.00)]
MERIDIAN = {"name": "Meridian Industrial Parts Co.",
            "address": ["88 Foundry Rd, Cleveland OH 44114", "Tax ID 27-5544321"]}
MER_FOOT = ["Remit to Bank of America, ABA 026009593, acct 330188420057. Net 60."]


def main() -> None:
    # 01 happy path: clean text PDF, explicit PO, matches exactly.
    draw_invoice(OUT / "01_happy_northwind.pdf", vendor=NORTHWIND, bill_to=ACME,
                 meta=[("Invoice #", "INV-0042"), ("Invoice date", "2026-11-03"), ("Due date", "2026-12-03"),
                       ("PO number", "PO-2026-0412")],
                 lines=NW_LINES, tax_label="Sales tax (8.25%)", tax_rate=0.0825, footer=NW_FOOT)

    # 02/03 split PO: part 1 bills 60 of 100 units (ok), part 2 bills 50 more (over-billing).
    for name, num, date, qty in (("02_split_meridian_part1.pdf", "MIP-7781", "2026-10-10", 60),
                                 ("03_split_meridian_part2.pdf", "MIP-7799", "2026-11-12", 50)):
        draw_invoice(OUT / name, vendor=MERIDIAN, bill_to=ACME, accent=colors.HexColor("#5a2d0c"),
                     meta=[("Invoice No.", num), ("Date", date), ("Customer PO", "PO-2026-0455"),
                           ("Terms", "Net 60")],
                     lines=[("MIP-SK-220", "Hydraulic pump seal kit HP-220", qty, 145.00)],
                     tax_label="Tax (0% - resale cert. on file)", tax_rate=0.0, footer=MER_FOOT)

    # 04 scanned, no PO reference: the PO must be inferred from vendor + line items.
    tmp = OUT / "_tmp4.pdf"
    draw_invoice(tmp, vendor={"name": "Brightline Logistics LLC",
                              "address": ["4100 W 47th St, Chicago IL 60632", "EIN 46-7788990  |  MC# 884213"]},
                 bill_to=ACME, accent=colors.HexColor("#0b5d3b"), show_sku=False,
                 meta=[("Invoice", "BL-26-10388"), ("Invoice date", "2026-11-06"), ("Ship ref", "Load batch 44")],
                 lines=[("", "FTL Chicago IL -> Dallas TX, 53' dry van", 4, 1850.00)],
                 tax_label="Tax", tax_rate=0.0,
                 footer=["Wire to Wells Fargo, routing 121000248, account 771203945. Net 45."])
    to_scan(tmp, OUT / "04_scanned_brightline_no_po.pdf", seed=4)

    # 05 disguised duplicate: invoice 01 re-sent as a scan, number reformatted INV-0042 -> INV42.
    tmp = OUT / "_tmp5.pdf"
    draw_invoice(tmp, vendor=NORTHWIND, bill_to=ACME,
                 meta=[("Invoice #", "INV42"), ("Invoice date", "2026-11-03"), ("Due date", "2026-12-03"),
                       ("PO number", "PO-2026-0412")],
                 lines=NW_LINES, tax_label="Sales tax (8.25%)", tax_rate=0.0825, footer=NW_FOOT)
    to_scan(tmp, OUT / "05_duplicate_northwind_resend.pdf", seed=5)

    # 06 bank details changed: amounts match the PO, but the remittance account is new.
    draw_invoice(OUT / "06_bank_change_cobalt.pdf",
                 vendor={"name": "Cobalt Cloud Services Ltd",
                         "address": ["21 Finsbury Square, London EC2A 1DX", "VAT GB 293 4471 02"]},
                 bill_to=ACME, cur="£", accent=colors.HexColor("#3b2a6b"),
                 meta=[("Invoice number", "CCS-INV-2611"), ("Invoice date", "2026-11-01"),
                       ("Billing period", "Nov 2026"), ("Your PO", "PO-2026-0478")],
                 lines=[("CCS-PLAT-ENT", "Platform subscription - Enterprise tier (Nov)", 1, 2400.00),
                        ("CCS-SUP-PREM", "Premium support (Nov)", 1, 350.00)],
                 tax_label="VAT (0% - reverse charge)", tax_rate=0.0,
                 footer=["IMPORTANT: our bank details have changed. Please update your records.",
                         "Pay to: Revolut Business, IBAN GB71 REVO 0099 7012 3456 78, BIC REVOGB21."])
    print("wrote", sorted(p.name for p in OUT.glob("*.pdf")))


if __name__ == "__main__":
    main()
