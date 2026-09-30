"""Invariants that make the ground-truth labels trustworthy: each invoice exhibits
exactly the discrepancy its label claims, and no other."""

import re
from collections import Counter, defaultdict
from decimal import Decimal

import pytest

from app.config import Settings
from app.models import Action, ExceptionCode as EC, POStatus
from data.generator.dataset import Dataset
from data.generator.generate import DEFAULT_OUT, DEFAULT_SEED, DISTRIBUTION, Generator, money

S = Settings()


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return Generator(seed=DEFAULT_SEED).build()


@pytest.fixture(scope="module")
def ctx(ds):
    pos = {p.po_number: p for p in ds.purchase_orders}
    grs = {g.po_number: g for g in ds.goods_receipts}
    rows = [(doc.invoice, label) for doc, label in zip(ds.invoices, ds.labels)]
    return pos, grs, rows


def expected_tax(inv) -> Decimal:
    return sum((money(l.total * S.vat_rate) for l in inv.line_items), Decimal("0"))


def test_distribution_and_alignment(ds):
    assert len(ds.invoices) == 500
    assert Counter(l.code.value for l in ds.labels) == Counter(DISTRIBUTION)
    assert [d.doc_id for d in ds.invoices] == [l.doc_id for l in ds.labels]
    assert all(d.invoice.invoice_number == l.invoice_number for d, l in zip(ds.invoices, ds.labels))


def test_deterministic(ds):
    assert Generator(seed=DEFAULT_SEED).build().model_dump_json() == ds.model_dump_json()
    assert Generator(seed=DEFAULT_SEED + 1).build().model_dump_json() != ds.model_dump_json()


def test_committed_dataset_is_current(ds):
    """data/synthetic/ must be regenerated whenever the generator changes."""
    assert Dataset.load(DEFAULT_OUT) == ds, "run: python -m data.generator.generate"


def test_write_load_roundtrip(ds, tmp_path):
    ds.write(tmp_path, {})
    assert Dataset.load(tmp_path) == ds


def test_invoice_arithmetic(ctx):
    for inv, _ in ctx[2]:
        for l in inv.line_items:
            assert l.total == money(l.quantity * l.unit_price)
        assert inv.subtotal == sum(l.total for l in inv.line_items)
        assert inv.total_amount == inv.subtotal + inv.tax_amount
        assert inv.due_date > inv.invoice_date


def test_tax(ctx):
    for inv, label in ctx[2]:
        if label.code == EC.E07:
            assert abs(inv.tax_amount - expected_tax(inv)) >= 1, label.doc_id
        else:
            assert inv.tax_amount == expected_tax(inv), label.doc_id


def test_amount_vs_po(ctx):
    pos, _, rows = ctx
    for inv, label in rows:
        if label.true_po_number is None:
            continue
        po = pos[label.true_po_number]
        delta = abs(inv.subtotal - po.total_amount)
        limit = S.default_tolerance.limit_for(po.total_amount)
        if label.code == EC.E01:
            assert po.total_amount * Decimal("0.001") <= delta <= limit, label.doc_id
        elif label.code == EC.E02:
            assert delta > limit and Decimal("0.025") <= delta / po.total_amount <= Decimal("0.16"), label.doc_id
        else:
            assert delta == 0, label.doc_id


def test_po_references(ctx):
    pos, _, rows = ctx
    digits = lambda s: re.sub(r"\D", "", s)
    for inv, label in rows:
        ref = inv.po_reference
        if label.code == EC.E05:
            assert ref not in pos, label.doc_id
            if label.variant == "maverick":
                assert label.true_po_number is None
        elif "po_ref_format_variant" in label.edge_cases:
            assert ref != label.true_po_number and digits(ref) == digits(label.true_po_number)
        else:
            assert ref == label.true_po_number, label.doc_id


def test_goods_receipts(ds, ctx):
    pos, grs, rows = ctx
    assert len(grs) == len(ds.goods_receipts), "at most one GR per PO"
    assert set(grs) <= set(pos)
    for inv, label in rows:
        if label.true_po_number is None:
            continue
        po, gr = pos[label.true_po_number], grs.get(label.true_po_number)
        if "no_goods_receipt" in label.edge_cases:
            assert gr is None
            continue
        assert gr is not None, label.doc_id
        short = any(g.quantity_received < p.quantity for g, p in zip(gr.line_items, po.line_items))
        if label.code == EC.E03 and label.variant == "partial_delivery":
            assert short and po.status == POStatus.PARTIALLY_FULFILLED
        else:
            assert not short, label.doc_id
        if label.variant == "gr_notes_only":
            assert gr.notes


def test_po_status(ctx):
    pos, _, rows = ctx
    for _, label in rows:
        if label.true_po_number:
            closed = pos[label.true_po_number].status == POStatus.CLOSED
            assert closed == (label.code == EC.E06), label.doc_id


def test_supplier_names(ctx):
    pos, _, rows = ctx
    for inv, label in rows:
        if label.true_po_number is None:
            continue
        po_name = pos[label.true_po_number].supplier_name
        if label.code == EC.E08 or "benign_name_variant" in label.edge_cases:
            assert inv.supplier_name != po_name, label.doc_id
        else:
            assert inv.supplier_name == po_name, label.doc_id


def test_duplicates_are_the_only_near_identical_invoices(ctx):
    _, _, rows = ctx
    index = {label.doc_id: i for i, (_, label) in enumerate(rows)}
    for i, (inv, label) in enumerate(rows):
        if label.code == EC.E04:
            orig, orig_label = rows[index[label.duplicate_of]]
            assert index[label.duplicate_of] < i, "duplicate must be processed after original"
            assert orig_label.code == EC.CLEAN
            assert (inv.supplier_name, inv.total_amount) == (orig.supplier_name, orig.total_amount)
            assert abs((inv.invoice_date - orig.invoice_date).days) <= 1

    groups = defaultdict(list)
    for inv, label in rows:
        groups[(inv.supplier_name, inv.total_amount)].append((inv.invoice_date, label))
    for items in groups.values():
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                (da, la), (db, lb) = items[a], items[b]
                if abs((da - db).days) <= S.duplicate_date_window_days:
                    assert EC.E04 in (la.code, lb.code), (la.doc_id, lb.doc_id)


def test_expected_actions(ds):
    want = {EC.CLEAN: Action.AUTO_APPROVE, EC.E01: Action.AUTO_APPROVE, EC.E04: Action.AUTO_REJECT}
    for label in ds.labels:
        assert label.action == want.get(label.code, Action.ESCALATE)
