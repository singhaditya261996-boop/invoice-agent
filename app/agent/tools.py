"""Agent tool definitions (PRD §3.2).

Data-access tools are deterministic lookups over an in-memory batch store. The two
LLM-backed tools live with their pipeline steps: extract_invoice_fields in extractor.py,
generate_escalation_brief in reporter.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz

from app.agent.normalize import canonical_po_ref, description_key, money, supplier_key
from app.models import GoodsReceipt, Invoice, InvoiceLineItem, POCandidate, PurchaseOrder

# Composite fuzzy-match weights (Step 2). Amount and supplier dominate; line items break ties.
W_NAME, W_AMOUNT, W_LINES, W_DATE = 0.40, 0.35, 0.15, 0.10
MIN_NAME_SIMILARITY = 0.6


@dataclass
class ProcessedInvoice:
    doc_id: str | None
    invoice: Invoice
    supplier_id: str | None  # from the matched PO, when there is one
    po_number: str | None
    verified: bool = True  # False: extraction was unreliable and the invoice awaits manual entry


class DataStore:
    """Holds the uploaded batch: POs, goods receipts, and previously processed invoices."""

    def __init__(
        self,
        pos: list[PurchaseOrder] | None = None,
        goods_receipts: list[GoodsReceipt] | None = None,
    ) -> None:
        self.pos = {po.po_number: po for po in pos or []}
        self.goods_receipts = {gr.po_number: gr for gr in goods_receipts or []}
        self.processed: list[ProcessedInvoice] = []

    def record(self, doc_id: str | None, invoice: Invoice, po: PurchaseOrder | None, verified: bool = True) -> None:
        self.processed.append(ProcessedInvoice(doc_id, invoice, po.supplier_id if po else None,
                                               po.po_number if po else None, verified))


def lookup_po(store: DataStore, po_number: str | None) -> PurchaseOrder | None:
    """Step 2: exact match on the reference, tolerating formatting (spaces, dashes, case)."""
    if not po_number or not po_number.strip():
        return None
    return store.pos.get(po_number.strip()) or store.pos.get(canonical_po_ref(po_number) or "")


def search_pos(
    store: DataStore,
    supplier_name: str,
    amount_range: tuple[Decimal, Decimal],
    date_range: tuple[date, date],
    descriptions: list[str] | None = None,
) -> list[POCandidate]:
    """Step 2 fuzzy fallback: POs within the amount and order-date windows, ranked by composite similarity."""
    lo, hi = amount_range
    target = (lo + hi) / 2
    half_width = (hi - lo) / 2
    name = supplier_key(supplier_name)
    inv_lines = {description_key(d) for d in descriptions or []}

    candidates = []
    for po in store.pos.values():
        if not (lo <= po.total_amount <= hi and date_range[0] <= po.order_date <= date_range[1]):
            continue
        name_sim = fuzz.token_set_ratio(name, supplier_key(po.supplier_name)) / 100
        if name_sim < MIN_NAME_SIMILARITY:
            continue
        amount_sim = float(1 - abs(po.total_amount - target) / half_width) if half_width else 1.0
        po_lines = {description_key(l.description) for l in po.line_items}
        line_sim = len(inv_lines & po_lines) / len(inv_lines | po_lines) if inv_lines else 0.0
        score = W_NAME * name_sim + W_AMOUNT * amount_sim + W_LINES * line_sim + W_DATE
        candidates.append(POCandidate(
            po_number=po.po_number,
            score=round(min(score, 1.0), 4),
            reasons=[
                f"supplier similarity {name_sim:.2f}",
                f"PO total £{po.total_amount} vs invoice £{target} ({float((po.total_amount - target) / target):+.1%})",
                f"line items overlap {line_sim:.0%}",
                f"ordered {po.order_date}",
            ],
        ))
    return sorted(candidates, key=lambda c: (-c.score, c.po_number))


def lookup_goods_receipt(store: DataStore, po_number: str) -> GoodsReceipt | None:
    """Step 3: quantity validation."""
    return store.goods_receipts.get(po_number)


def check_duplicate(
    store: DataStore,
    supplier_id: str | None,
    supplier_name: str,
    amount: Decimal,
    date_range: tuple[date, date],
    invoice_number: str | None = None,
    po_number: str | None = None,
    po_reference: str | None = None,
) -> list[tuple[ProcessedInvoice, str]]:
    """Step 3: prior invoices that may be the same bill. Returns (prior, basis) pairs.

    basis "amount": same supplier, same total, within the date window (the PRD rule).
    basis "po": same PO and same total on any date. A PO billed in full once should not be billed
    again for the same amount; this also survives a misread invoice date.
    basis "invoice_number": same supplier and invoice number, any amount.
    basis "unverified": the prior awaits manual entry, so its fields may be misread; a similar supplier
    name plus any one of invoice number, PO reference, or amount-and-date is enough.
    Supplier identity uses the PO's supplier_id when both matched a PO, otherwise the
    formatting-insensitive supplier name.
    """
    name = supplier_key(supplier_name)
    in_window = lambda d: date_range[0] <= d <= date_range[1]  # noqa: E731
    hits = []
    for prior in store.processed:
        p = prior.invoice
        prior_name = supplier_key(p.supplier_name)
        if not prior.verified:
            # Any field of an unverified prior may be misread, so any one strong link is enough to hold this
            # invoice for a human (never to auto-reject it).
            if fuzz.ratio(prior_name, name) >= 90 and (
                    (invoice_number and p.invoice_number == invoice_number)
                    or (po_reference and (p.po_reference or "").strip() == po_reference.strip())
                    or (p.total_amount == amount and in_window(p.invoice_date))):
                hits.append((prior, "unverified"))
            continue
        same_supplier = (supplier_id is not None and prior.supplier_id == supplier_id) or prior_name == name
        if not same_supplier:
            continue
        if p.total_amount == amount and in_window(p.invoice_date):
            hits.append((prior, "amount"))
        elif po_number and prior.po_number == po_number and p.total_amount == amount:
            hits.append((prior, "po"))
        elif invoice_number and p.invoice_number == invoice_number:
            hits.append((prior, "invoice_number"))
    return hits


def recalculate_tax(line_items: list[InvoiceLineItem], vat_rate: Decimal) -> Decimal:
    """Step 3: expected VAT, rounded per line (UK practice) and summed."""
    return sum((money(line.total * vat_rate) for line in line_items), Decimal("0"))
