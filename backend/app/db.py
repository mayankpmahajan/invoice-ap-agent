"""SQLite (async) data model: procurement master data, the invoice ledger, runs and their stage events."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app import settings

engine = create_async_engine(settings.DATABASE_URL)
Session = async_sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


class Vendor(Base):
    __tablename__ = "vendors"
    vendor_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    tax_id: Mapped[str]
    country: Mapped[str]
    currency: Mapped[str]
    bank_name: Mapped[str]
    bank_account: Mapped[str]
    status: Mapped[str]  # approved | blocked
    payment_terms_days: Mapped[int]


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    po_number: Mapped[str] = mapped_column(String, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"))
    issue_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str]
    status: Mapped[str]  # open | closed
    description: Mapped[str]


class POLine(Base):
    __tablename__ = "po_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), index=True)
    line_no: Mapped[int]
    sku: Mapped[str | None]
    description: Mapped[str]
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str]
    file_hash: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued | running | completed | failed
    current_stage: Mapped[str | None]
    pdf_kind: Mapped[str | None]
    decision: Mapped[str | None]  # approved | needs_review | rejected
    decision_summary: Mapped[str | None] = mapped_column(Text)
    vendor_name: Mapped[str | None]
    invoice_number: Mapped[str | None]
    total: Mapped[float | None]
    currency: Mapped[str | None]
    po_number: Mapped[str | None]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    reviewer_action: Mapped[str | None]  # approved | rejected (human decision on a held invoice)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    stage: Mapped[str]
    status: Mapped[str]  # started | completed | failed | skipped
    title: Mapped[str]
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerInvoice(Base):
    """Every invoice the pipeline has decided on - the memory behind duplicate and PO-balance checks."""

    __tablename__ = "ledger_invoices"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    vendor_id: Mapped[str | None] = mapped_column(String, index=True)
    invoice_number: Mapped[str | None]
    invoice_number_norm: Mapped[str | None] = mapped_column(String, index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[float | None] = mapped_column(Float)
    net_amount: Mapped[float | None] = mapped_column(Float)  # pre-tax amount billed against the PO
    currency: Mapped[str | None]
    po_number: Mapped[str | None] = mapped_column(String, index=True)
    file_hash: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str]  # approved | needs_review | rejected
    po_line_quantities: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # {po_line_id: qty billed}


async def init_db(reset: bool = False) -> None:
    async with engine.begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s:
        if (await s.scalar(select(func.count()).select_from(Vendor))) == 0:
            await _seed(s)


async def _seed(s: AsyncSession) -> None:
    def rows(name: str):
        with open(settings.SEED_DIR / name, newline="") as f:
            return list(csv.DictReader(f))

    s.add_all(Vendor(**{**r, "payment_terms_days": int(r["payment_terms_days"])}) for r in rows("vendors.csv"))
    s.add_all(PurchaseOrder(**{**r, "issue_date": date.fromisoformat(r["issue_date"])}) for r in rows("purchase_orders.csv"))
    s.add_all(POLine(po_number=r["po_number"], line_no=int(r["line_no"]), sku=r["sku"] or None,
                     description=r["description"], quantity=float(r["quantity"]), unit_price=float(r["unit_price"]))
              for r in rows("po_lines.csv"))
    await s.commit()
