"""Step 1: Extract. Raw invoice -> structured Invoice.

- Structured input (Invoice, or a JSON dict) is validated directly: no LLM needed.
- Unstructured input (PDF bytes or document text) goes through Claude with structured output.

Fallback: when extraction confidence is below min_extraction_confidence, or the document
cannot be read at all, the invoice is flagged for manual data entry rather than matched
on possibly-wrong data (failure taxonomy: extraction hallucination).
"""

from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.agent.llm import LLM
from app.agent.normalize import money
from app.config import Settings
from app.models import ExtractionResult, Invoice, InvoiceLineItem

EXTRACT_SYSTEM = """You extract fields from supplier invoices for an accounts-payable system. Copy every \
value exactly as printed on the document. Do not correct, recompute, or infer values: if the VAT or a total \
looks wrong, copy it as printed, because downstream checks rely on seeing the document's own figures. \
Copy the purchase order reference exactly as printed, including any formatting; use null if none is \
printed, or the printed text if it is a placeholder such as "N/A". Give amounts as plain decimals without \
currency symbols or thousands separators, and dates as YYYY-MM-DD. For each line, 'total' is the net line \
amount before VAT. List in unreadable_fields any field you could not read with certainty, and set \
confidence to your overall certainty that every field is correct."""

_MONEY = {"type": "string", "description": "decimal, e.g. 1234.50"}
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string"},
        "supplier_name": {"type": "string"},
        "po_reference": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "invoice_date": {"type": "string", "description": "YYYY-MM-DD"},
        "due_date": {"type": "string", "description": "YYYY-MM-DD"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": _MONEY,
                    "unit_price": _MONEY,
                    "tax": _MONEY,
                    "total": _MONEY,
                },
                "required": ["description", "quantity", "unit_price", "tax", "total"],
                "additionalProperties": False,
            },
        },
        "subtotal": _MONEY,
        "tax_amount": _MONEY,
        "total_amount": _MONEY,
        "currency": {"type": "string"},
        "unreadable_fields": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["invoice_number", "supplier_name", "po_reference", "invoice_date", "due_date", "line_items",
                 "subtotal", "tax_amount", "total_amount", "currency", "unreadable_fields", "confidence"],
    "additionalProperties": False,
}

# Each internal inconsistency found in an extracted document reduces confidence.
INCONSISTENCY_PENALTY = 0.7


def extract_invoice_fields(
    raw: Invoice | dict | str | bytes,
    settings: Settings,
    llm: LLM | None = None,
) -> ExtractionResult:
    if isinstance(raw, Invoice):
        return ExtractionResult(invoice=raw, confidence=1.0, method="structured")
    if isinstance(raw, dict):
        return _from_structured(raw.get("invoice", raw))
    return _from_document(raw, settings, llm)


def _from_structured(data: dict) -> ExtractionResult:
    try:
        return ExtractionResult(invoice=Invoice.model_validate(data), confidence=1.0, method="structured")
    except ValidationError as e:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in e.errors()})
        return ExtractionResult(invoice=None, confidence=0.0, missing_fields=fields, method="structured",
                                needs_manual_entry=True, issues=["Structured invoice failed schema validation"])


def _from_document(raw: str | bytes, settings: Settings, llm: LLM | None) -> ExtractionResult:
    if llm is None:
        return ExtractionResult(invoice=None, confidence=0.0, method="llm", needs_manual_entry=True,
                                issues=["Unstructured document and no LLM available (offline mode)"])
    if isinstance(raw, bytes) and raw.startswith(b"%PDF"):
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(raw).decode()}},
            {"type": "text", "text": "Extract the invoice fields from this document."},
        ]
    else:
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        content = f"<invoice_document>\n{text}\n</invoice_document>"

    data = llm.json("extract", EXTRACT_SYSTEM, content, EXTRACT_SCHEMA)
    if data is None:
        return ExtractionResult(invoice=None, confidence=0.0, method="llm", needs_manual_entry=True,
                                issues=["LLM extraction unavailable"])
    try:
        invoice = Invoice(
            invoice_number=data["invoice_number"],
            supplier_name=data["supplier_name"],
            po_reference=data["po_reference"],
            invoice_date=date.fromisoformat(data["invoice_date"]),
            due_date=date.fromisoformat(data["due_date"]),
            line_items=[InvoiceLineItem(**{k: (_dec(v) if k != "description" else v) for k, v in l.items()})
                        for l in data["line_items"]],
            subtotal=_dec(data["subtotal"]),
            tax_amount=_dec(data["tax_amount"]),
            total_amount=_dec(data["total_amount"]),
            currency=data["currency"] or "GBP",
        )
    except (ValueError, InvalidOperation, ValidationError, KeyError, TypeError) as e:
        return ExtractionResult(invoice=None, confidence=0.0, method="llm", needs_manual_entry=True,
                                missing_fields=list(data.get("unreadable_fields", [])),
                                issues=[f"Extracted fields could not be parsed: {e}"])

    issues = _consistency_issues(invoice)
    confidence = max(0.0, min(1.0, float(data["confidence"]))) * INCONSISTENCY_PENALTY ** len(issues)
    unreadable = list(data["unreadable_fields"])
    return ExtractionResult(
        invoice=invoice,
        confidence=round(confidence, 4),
        missing_fields=unreadable,
        issues=issues,
        method="llm",
        needs_manual_entry=confidence < settings.min_extraction_confidence or bool(unreadable),
    )


def _dec(value: str) -> Decimal:
    return Decimal(str(value).replace(",", "").replace("£", "").strip())


def _consistency_issues(inv: Invoice) -> list[str]:
    """Arithmetic the document must satisfy regardless of any tax error. A failure means a misread."""
    issues = [f"Line {i + 1}: {l.quantity} x £{l.unit_price} != £{l.total}"
              for i, l in enumerate(inv.line_items) if money(l.quantity * l.unit_price) != l.total]
    if sum((l.total for l in inv.line_items), Decimal(0)) != inv.subtotal:
        issues.append("Line totals do not sum to the subtotal")
    if inv.subtotal + inv.tax_amount != inv.total_amount:
        issues.append("Subtotal + VAT does not equal the total")
    return issues
