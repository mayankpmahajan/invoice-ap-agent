"""PDF ingestion: hash, page images, and the PDF's own text layer (ground truth when present)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from app import settings


@dataclass
class Page:
    number: int
    image_path: Path
    text: str

    @property
    def has_text_layer(self) -> bool:
        return len(self.text.strip()) >= settings.TEXT_LAYER_MIN_CHARS_PER_PAGE


@dataclass
class IngestedPdf:
    sha256: str
    pages: list[Page]

    @property
    def kind(self) -> str:
        with_text = sum(p.has_text_layer for p in self.pages)
        if with_text == len(self.pages):
            return "digital"
        return "scanned" if with_text == 0 else "mixed"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest(pdf_bytes: bytes) -> IngestedPdf:
    """Raises pdfium.PdfiumError on a corrupt / non-PDF file (caller routes it to a failed run)."""
    digest = sha256_bytes(pdf_bytes)
    doc = pdfium.PdfDocument(pdf_bytes)
    out_dir = settings.PAGE_IMAGE_DIR / digest
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[Page] = []
    for i, page in enumerate(doc, start=1):
        img_path = out_dir / f"page-{i}.png"
        if not img_path.exists():
            page.render(scale=settings.PDF_RENDER_DPI / 72).to_pil().save(img_path)
        text = page.get_textpage().get_text_range()
        pages.append(Page(number=i, image_path=img_path, text=text))
    return IngestedPdf(sha256=digest, pages=pages)


def normalize_ws(s: str) -> str:
    return " ".join(s.split())


def quote_in_text_layer(quote: str | None, page_text: str) -> bool:
    """Exact match after whitespace normalisation only - never fuzzy."""
    if not quote:
        return False
    return normalize_ws(quote) in normalize_ws(page_text)
