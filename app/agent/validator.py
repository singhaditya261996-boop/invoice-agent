"""Step 3: Validate (three-way match). Deterministic rules, plus the LLM for free-text GR notes.

Checks: PO reference, PO status, supplier name, amount vs tolerance, line items and
quantities vs PO and goods receipt, GR notes, tax recalculation, and duplicates.
Each finding is a field-level Discrepancy carrying its own evidence strength.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from rapidfuzz import fuzz

from app.agent.llm import LLM
from app.agent.normalize import description_key, gbp, money, supplier_key
from app.agent.tools import DataStore, check_duplicate, lookup_goods_receipt, recalculate_tax
from app.config import Settings
from app.models import (
    Discrepancy,
    ExceptionCode as EC,
    GoodsReceipt,
    Invoice,
    MatchResult,
    POStatus,
    ValidationResult,
)

# ---------------------------------------------------------------------------- GR notes

GR_NOTES_SYSTEM = """You read goods-receipt notes written by warehouse and reception staff when a delivery \
is booked in. Decide whether the note says that fewer units were accepted than were delivered or ordered \
(short delivery, backorder, items returned, rejected or damaged). Notes that only describe where or how \
goods arrived, or confirm a full delivery, do not indicate a shortfall. Report the number of units not \
received only if the note states it."""

GR_NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "indicates_shortfall": {"type": "boolean"},
        "units_not_received": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "explanation": {"type": "string"},
    },
    "required": ["indicates_shortfall", "units_not_received", "explanation"],
    "additionalProperties": False,
}

_SHORTFALL_WORDS = re.compile(
    r"\b(returned|return|rejected|damaged|missing|short|backorder|back-order|partial|faulty|sent back)\b", re.I)
_UNITS = re.compile(r"(\d+)\s*(?:units?\b|x\b|missing\b)", re.I)


@dataclass
class NotesReading:
    indicates_shortfall: bool
    units: int | None
    explanation: str
    used_llm: bool


def read_gr_notes(notes: str, llm: LLM | None) -> NotesReading | None:
    if not notes.strip():
        return None
    if llm:
        data = llm.json("gr_notes", GR_NOTES_SYSTEM, f"Goods receipt note:\n{notes}", GR_NOTES_SCHEMA)
        if data is not None:
            return NotesReading(data["indicates_shortfall"], data["units_not_received"], data["explanation"], True)
    shortfall = bool(_SHORTFALL_WORDS.search(notes))
    units = _UNITS.search(notes)
    return NotesReading(shortfall, int(units.group(1)) if units and shortfall else None,
                        "keyword match" if shortfall else "no shortfall language", False)


# ---------------------------------------------------------------------------- validate


def validate(
    invoice: Invoice,
    match: MatchResult,
    store: DataStore,
    settings: Settings,
    llm: LLM | None = None,
) -> ValidationResult:
    found: list[Discrepancy] = []
    checked: list[str] = []
    po = match.matched_po

    # PO reference (E05)
    if match.method not in ("exact", "exact_normalized"):
        ref = invoice.po_reference
        missing = not ref or not ref.strip() or not re.search(r"\d", ref)
        suggestion = f"; closest PO by supplier, amount and lines is {po.po_number} (score {match.score:.2f})" if po else ""
        found.append(Discrepancy(
            check="po_reference", field="po_reference", invoice_value=ref,
            detail=("Invoice does not quote a PO number" if missing
                    else f"PO reference {ref!r} does not exist") + suggestion,
            suggested_code=EC.E05, confidence=0.97 if missing else 0.93,
        ))

    gr = None
    if po:
        # PO status (E06)
        checked.append(f"PO status: {po.status.value}")
        if po.status == POStatus.CLOSED:
            found.append(Discrepancy(
                check="po_status", field="status", reference_value=po.status.value,
                detail=f"PO {po.po_number} is already closed (fully fulfilled)",
                suggested_code=EC.E06, confidence=0.98,
            ))

        # Supplier name (E08)
        found += _check_supplier(invoice, po.supplier_name, checked)

        # Amount vs tolerance (E01 / E02)
        found += _check_amount(invoice, po, settings, checked)

        # Line items and quantities vs PO and GR (E03), GR notes (LLM)
        gr = lookup_goods_receipt(store, po.po_number)
        found += _check_quantities(invoice, po, gr, llm, checked)

    # Tax (E07): independent of the PO
    found += _check_tax(invoice, settings, checked)

    # Duplicates (E04)
    found += _check_duplicate(invoice, po, store, settings, checked)

    return ValidationResult(discrepancies=found, checks_performed=checked, goods_receipt=gr)


def _check_supplier(invoice: Invoice, po_name: str, checked: list[str]) -> list[Discrepancy]:
    if supplier_key(invoice.supplier_name) == supplier_key(po_name):
        note = "exact" if invoice.supplier_name == po_name else "formatting difference only"
        checked.append(f"Supplier name matches PO ({note})")
        return []
    similarity = fuzz.ratio(supplier_key(invoice.supplier_name), supplier_key(po_name)) / 100
    # A near-identical spelling is weaker evidence of a different entity than a different name altogether.
    return [Discrepancy(
        check="supplier_name", field="supplier_name", invoice_value=invoice.supplier_name, reference_value=po_name,
        detail=f"Invoice supplier {invoice.supplier_name!r} vs PO supplier {po_name!r} (similarity {similarity:.2f})",
        suggested_code=EC.E08, confidence=0.85 if similarity >= 0.85 else 0.95,
    )]


def _check_amount(invoice: Invoice, po, settings: Settings, checked: list[str]) -> list[Discrepancy]:
    delta = invoice.subtotal - po.total_amount
    limit = money(settings.tolerance_for(po.supplier_id, po.cost_centre).limit_for(po.total_amount))
    if delta == 0:
        checked.append(f"Subtotal {gbp(invoice.subtotal)} equals PO total")
        return []
    pct = delta / po.total_amount
    within = abs(delta) <= limit
    return [Discrepancy(
        check="amount", field="subtotal", invoice_value=str(invoice.subtotal), reference_value=str(po.total_amount),
        detail=(f"Invoice subtotal {gbp(invoice.subtotal)} vs PO total {gbp(po.total_amount)}: "
                f"difference {gbp(delta, signed=True)} ({pct:+.2%}), tolerance {gbp(limit)}"),
        suggested_code=EC.E01 if within else EC.E02, confidence=0.97,
    )]


def _check_quantities(invoice: Invoice, po, gr: GoodsReceipt | None, llm: LLM | None,
                      checked: list[str]) -> list[Discrepancy]:
    found = []
    po_lines = {description_key(l.description): l for l in po.line_items}
    gr_lines = {description_key(l.description): l for l in gr.line_items} if gr else {}
    if gr:
        checked.append(f"Goods receipt {gr.gr_number} on file (received {gr.receipt_date}, by {gr.receiver})")
    else:
        checked.append("Goods receipt: none on file, so quantities could not be confirmed")

    short_lines = 0
    for line in invoice.line_items:
        key = description_key(line.description)
        po_line = po_lines.get(key)
        if po_line is None:
            found.append(Discrepancy(
                check="line_items", field="line_items", invoice_value=line.description,
                detail=f"Invoice line {line.description!r} ({gbp(line.total)}) is not on PO {po.po_number}",
                suggested_code=EC.E02, confidence=0.9,
            ))
            continue
        if line.quantity != po_line.quantity:
            found.append(Discrepancy(
                check="quantity", field=f"quantity: {line.description}", invoice_value=str(line.quantity),
                reference_value=str(po_line.quantity),
                detail=f"{line.description}: invoiced {line.quantity}, PO ordered {po_line.quantity}",
                suggested_code=EC.E03, confidence=0.95,
            ))
        gr_line = gr_lines.get(key)
        if gr and gr_line is not None and line.quantity > gr_line.quantity_received:
            short_lines += 1
            found.append(Discrepancy(
                check="quantity", field=f"quantity: {line.description}", invoice_value=str(line.quantity),
                reference_value=str(gr_line.quantity_received),
                detail=f"{line.description}: invoiced {line.quantity}, goods receipt shows {gr_line.quantity_received} received",
                suggested_code=EC.E03, confidence=0.95,
            ))

    if gr and gr.notes.strip():
        reading = read_gr_notes(gr.notes, llm)
        how = "the AI model" if reading.used_llm else "keyword rules"
        checked.append(f"GR notes {gr.notes!r} read by {how}: "
                       f"{'shortfall reported' if reading.indicates_shortfall else 'no shortfall'}")
        if reading.indicates_shortfall and not short_lines:
            # Failure taxonomy: notes and structured data conflict -> escalate, do not guess
            units = f"{reading.units} units" if reading.units else "units"
            found.append(Discrepancy(
                check="gr_notes", field="goods_receipt.notes", invoice_value=gr.notes,
                detail=(f"Goods receipt notes report {units} not accepted ({gr.notes!r}), "
                        "but the structured GR quantities show full receipt"),
                suggested_code=EC.E03, confidence=0.85 if reading.used_llm else 0.75,
            ))
    return found


def _check_tax(invoice: Invoice, settings: Settings, checked: list[str]) -> list[Discrepancy]:
    found = []
    expected = recalculate_tax(invoice.line_items, settings.vat_rate)
    diff = invoice.tax_amount - expected
    if abs(diff) <= settings.tax_rounding_tolerance:
        checked.append(f"VAT {gbp(invoice.tax_amount)} matches recalculation at {settings.vat_rate:.0%}")
    else:
        implied = invoice.tax_amount / invoice.subtotal if invoice.subtotal else Decimal(0)
        found.append(Discrepancy(
            check="tax", field="tax_amount", invoice_value=str(invoice.tax_amount), reference_value=str(expected),
            detail=(f"Stated VAT {gbp(invoice.tax_amount)} vs {gbp(expected)} recalculated at {settings.vat_rate:.0%} "
                    f"(difference {gbp(diff, signed=True)}; stated amount implies {implied:.1%})"),
            suggested_code=EC.E07, confidence=0.96,
        ))
    if invoice.subtotal + invoice.tax_amount != invoice.total_amount:
        found.append(Discrepancy(
            check="tax", field="total_amount", invoice_value=str(invoice.total_amount),
            reference_value=str(invoice.subtotal + invoice.tax_amount),
            detail=f"Total {gbp(invoice.total_amount)} does not equal subtotal + VAT ({gbp(invoice.subtotal + invoice.tax_amount)})",
            suggested_code=EC.E07, confidence=0.9,
        ))
    return found


def _check_duplicate(invoice: Invoice, po, store: DataStore, settings: Settings,
                     checked: list[str]) -> list[Discrepancy]:
    window = timedelta(days=settings.duplicate_date_window_days)
    hits = check_duplicate(store, po.supplier_id if po else None, invoice.supplier_name, invoice.total_amount,
                           (invoice.invoice_date - window, invoice.invoice_date + window), invoice.invoice_number,
                           po.po_number if po else None, invoice.po_reference)
    if not hits:
        checked.append(f"No prior invoice from this supplier for {gbp(invoice.total_amount)} "
                       f"within ±{settings.duplicate_date_window_days} day(s), or with the same invoice number")
        return []
    prior, basis = hits[0]
    same_number = prior.invoice.invoice_number == invoice.invoice_number
    same_po = po is not None and prior.po_number == po.po_number
    ref = f"{prior.doc_id} / {prior.invoice.invoice_number}" if prior.doc_id else prior.invoice.invoice_number
    if not prior.verified:
        # The prior's data is unreliable, so never auto-reject on it; but never let this through either.
        confidence = 0.8
        detail = (f"Resembles invoice {prior.invoice.invoice_number} ({prior.doc_id}), which is awaiting manual "
                  "data entry (same supplier and invoice number, PO reference, or amount); this may be a "
                  "resubmission of it")
    elif basis == "po":
        # Could be a resubmission (or a misread date); could be a legitimate equal instalment. A human decides.
        days = abs((invoice.invoice_date - prior.invoice.invoice_date).days)
        confidence = 0.8
        detail = (f"Same PO {po.po_number} and amount ({gbp(invoice.total_amount)}) as prior invoice "
                  f"{prior.invoice.invoice_number}, dated {days} days apart")
    elif basis == "invoice_number":
        confidence = 0.8
        detail = (f"Same supplier and invoice number as prior invoice {prior.invoice.invoice_number} "
                  f"({prior.invoice.invoice_date}), but a different amount ({gbp(prior.invoice.total_amount)})")
    else:
        # Failure taxonomy: a different PO suggests a legitimate recurring charge, not a resubmission.
        confidence = 0.98 if same_number and same_po else 0.93 if same_po else 0.9 if same_number else 0.7
        detail = (f"Matches prior invoice {prior.invoice.invoice_number} ({prior.invoice.invoice_date}, "
                  f"{gbp(prior.invoice.total_amount)}): same supplier and amount"
                  f"{', same invoice number' if same_number else ''}{', same PO' if same_po else ', different PO'}")
    return [Discrepancy(
        check="duplicate", field="invoice", invoice_value=invoice.invoice_number, reference_value=ref,
        detail=detail, suggested_code=EC.E04, confidence=confidence,
    )]
