from datetime import date

from app import rules
from app.schemas import AmountField, InvoiceExtraction, LineItem, TextField


def tf(v, c="sure"):
    return TextField(value=v, confidence=c, page=1, quote=v)


def af(v, c="sure"):
    return AmountField(value=v, confidence=c, page=1, quote=None)


def inv(number="INV-0042", qty=60, price=145.0, bank=None, total=None, po="PO-1"):
    sub = qty * price
    return InvoiceExtraction(
        document_type="invoice", vendor_name=tf("Meridian"), vendor_tax_id=tf("27-5544321"),
        vendor_bank_account=tf(bank), invoice_number=tf(number), invoice_date=tf("2026-11-01"),
        due_date=tf(None), currency=tf("USD"), po_reference=tf(po),
        line_items=[LineItem(description="Seal kit", sku="SK", quantity=qty, unit_price=price, amount=sub, page=1,
                             quote="x", confidence="sure")],
        subtotal=af(sub), tax_amount=af(0), total=af(total if total is not None else sub),
        amounts_include_tax=False, doubts="")


VENDOR = rules.VendorRec("V-1", "Meridian", "27-5544321", "026009593-330188420057", "approved", "USD")
PO = rules.PORec("PO-1", "V-1", "USD", "open", [rules.POLineRec("PO-1#1", "SK", "Seal kit", 100, 145.0)])


def ledger(**kw):
    base = dict(run_id="r0", vendor_id="V-1", invoice_number="MIP-1", invoice_number_norm="MIP1",
                invoice_date=date(2026, 10, 1), total=8700.0, net_amount=8700.0, po_number="PO-1",
                file_hash="h0", status="approved", po_line_quantities={"PO-1#1": 60})
    return rules.LedgerRec(**{**base, **kw})


def test_invoice_number_normalisation_ignores_formatting():
    assert rules.norm_invoice_number("INV-0042") == rules.norm_invoice_number("inv 42") == rules.norm_invoice_number("INV42")
    assert rules.norm_invoice_number("INV-0042") != rules.norm_invoice_number("INV-0043")


def test_tolerance_needs_both_bounds():
    assert rules.within_tolerance(1015, 1000)        # 1.5% and 15 absolute
    assert not rules.within_tolerance(1040, 1000)    # within 50 absolute but 4%
    assert not rules.within_tolerance(10150, 10000)  # 1.5% but 150 absolute
    assert not rules.within_tolerance(54.0, 4.75)    # one item at ~11x the PO price, under 50 absolute
    assert rules.within_tolerance(100.01, 100.0)     # rounding


def test_flagged_checks_do_not_keep_pass_wording():
    dup = rules.check_duplicate(inv(), "V-1", "h1", [ledger(invoice_number="INV-0042", invoice_number_norm="INV42")])
    assert (dup.outcome, dup.title) == ("reject", "Duplicate invoice")
    near = rules.check_duplicate(inv(number="X-9", total=8700.0), "V-1", "h1", [ledger(invoice_date=date(2026, 11, 1))])
    assert (near.outcome, near.title) == ("review", "Possible duplicate")
    over = {c.id: c for c in rules.check_lines_against_po(PO, inv(qty=50), ["PO-1#1"], [ledger()])}["po_balance"]
    assert over.title == "Over-billing the PO"
    ok = rules.check_duplicate(inv(), "V-1", "h1", [])
    assert (ok.outcome, ok.title) == ("pass", "Not a duplicate")


def test_split_po_within_balance_passes_and_overbilling_is_held():
    ok = rules.check_lines_against_po(PO, inv(qty=40), ["PO-1#1"], [ledger()])
    assert {c.id: c.outcome for c in ok}["po_balance"] == "pass"
    over = rules.check_lines_against_po(PO, inv(qty=50), ["PO-1#1"], [ledger()])
    assert {c.id: c.outcome for c in over}["po_balance"] == "review"


def test_rejected_prior_invoices_do_not_consume_balance():
    checks = rules.check_lines_against_po(PO, inv(qty=50), ["PO-1#1"], [ledger(status="rejected")])
    assert {c.id: c.outcome for c in checks}["po_balance"] == "pass"


def test_duplicate_by_reformatted_number_is_rejected():
    c = rules.check_duplicate(inv(number="mip 0001"), "V-1", "new-hash", [ledger()])
    assert c.outcome == "reject"


def test_same_amount_different_number_is_review_not_reject():
    c = rules.check_duplicate(inv(number="MIP-9", total=8700.0), "V-1", "new-hash", [ledger(invoice_date=date(2026, 10, 20))])
    assert c.outcome == "review"


def test_bank_change_is_held():
    assert rules.check_bank_details(VENDOR, inv(bank="GB71 REVO 0099 7012 3456 78")).outcome == "review"
    assert rules.check_bank_details(VENDOR, inv(bank="026009593 / 330188420057")).outcome == "pass"
    assert rules.check_bank_details(VENDOR, inv(bank=None)).outcome == "info"


def test_price_variance_beyond_tolerance_is_held():
    checks = rules.check_lines_against_po(PO, inv(qty=10, price=160.0), ["PO-1#1"], [])
    assert {c.id: c.outcome for c in checks}["price_variance"] == "review"


def test_unknown_or_blocked_vendor_rejected():
    assert rules.check_vendor(None, inv()).outcome == "reject"
    blocked = rules.VendorRec("V-5", "Apex", "1", "1", "blocked", "USD")
    assert rules.check_vendor(blocked, inv()).outcome == "reject"


def test_arithmetic_mismatch_held():
    bad = inv()
    bad.total.value = bad.subtotal.value + 100
    assert rules.check_arithmetic(bad).outcome == "review"


def test_decision_precedence():
    mk = lambda o: rules.Check("x", "x", o, o)
    assert rules.decide([mk("pass"), mk("review"), mk("reject")])[0] == "rejected"
    assert rules.decide([mk("pass"), mk("review")])[0] == "needs_review"
    assert rules.decide([mk("pass"), mk("info")])[0] == "approved"


def test_invoice_number_segments_are_identity():
    assert rules.norm_invoice_number("2026-1-15") != rules.norm_invoice_number("2026-11-5")
    assert rules.norm_invoice_number("INV-1-02") != rules.norm_invoice_number("INV-10-2")


def test_differently_split_number_is_a_near_duplicate_hold_not_a_reject():
    c = rules.check_duplicate(inv(number="INV-10-2"), "V-1", "h1",
                              [ledger(invoice_number="INV-1-02", invoice_date=date(2025, 1, 1), total=1.0)])
    assert (c.outcome, c.evidence["match"]) == ("review", "near-number")


def test_dates_outside_plausible_window_are_held():
    po = rules.PORec("PO-1", "V-1", "USD", "open", PO.lines, date(2026, 10, 1))
    today = date(2026, 11, 28)
    assert rules.check_dates(inv(), po, today).outcome == "pass"  # invoice dated 2026-11-01
    future = inv(); future.invoice_date.value = "2031-01-01"
    stale = inv(); stale.invoice_date.value = "2019-05-01"
    early = inv(); early.invoice_date.value = "2026-09-20"
    for ex in (future, stale, early):
        assert rules.check_dates(ex, po, today).outcome == "review", ex.invoice_date.value


def test_tax_id_mismatch_is_held_and_labels_are_ignored():
    assert rules.check_tax_id(VENDOR, inv()).outcome == "pass"
    labelled = inv(); labelled.vendor_tax_id.value = "Tax ID 27-5544321"
    assert rules.check_tax_id(VENDOR, labelled).outcome == "pass"
    wrong = inv(); wrong.vendor_tax_id.value = "99-0000001"
    assert rules.check_tax_id(VENDOR, wrong).outcome == "review"


def _outcomes(ex, line_map=("PO-1#1",)):
    return {c.id: c.outcome for c in rules.check_lines_against_po(PO, ex, list(line_map), [])}


def test_empty_lump_sum_or_negative_lines_are_held():
    empty = inv(); empty.line_items = []
    assert _outcomes(empty, ())["line_detail"] == "review"
    lump = inv(); lump.line_items[0].quantity = None
    assert _outcomes(lump)["line_detail"] == "review"
    neg = inv(qty=-5)
    assert _outcomes(neg)["line_detail"] == "review"


def test_close_price_inside_tolerance_is_noted_not_held():
    close = _outcomes(inv(qty=30, price=145.5))  # +15.00 on 4,350 (0.3%)
    assert close["price_variance"] == "info" and "line_detail" not in close
    assert _outcomes(inv(qty=30))["price_variance"] == "pass"


def test_headline_names_the_deciding_reason():
    held = rules.check_lines_against_po(PO, inv(qty=50), ["PO-1#1"], [ledger()])
    decision, headline, _ = rules.decide(held)
    assert decision == "needs_review" and headline == "Held for a person: Over-billing the PO"
    assert rules.decide([rules.Check("a", "A", "pass", "ok")])[1] == "Approved: all 1 checks passed"
