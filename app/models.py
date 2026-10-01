"""Core data model (PRD §2.1), exception taxonomy (§2.2), and pipeline output types (§3.1, §7.2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Source documents (PRD §2.1)
# ---------------------------------------------------------------------------


class POStatus(str, Enum):
    OPEN = "Open"
    PARTIALLY_FULFILLED = "Partially Fulfilled"
    CLOSED = "Closed"


class POLineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


class PurchaseOrder(BaseModel):
    po_number: str
    supplier_name: str
    supplier_id: str
    order_date: date
    delivery_date: date
    line_items: list[POLineItem]
    total_amount: Decimal
    currency: str = "GBP"
    cost_centre: str
    approver: str
    payment_terms: str
    status: POStatus


class InvoiceLineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax: Decimal
    total: Decimal  # net: quantity * unit_price, excl. tax


class Invoice(BaseModel):
    invoice_number: str
    supplier_name: str  # may differ slightly from PO (Ltd, plc, typos)
    po_reference: str | None  # may be missing, truncated, or wrong
    invoice_date: date
    due_date: date
    line_items: list[InvoiceLineItem]
    subtotal: Decimal  # pre-tax; compared against PurchaseOrder.total_amount
    tax_amount: Decimal
    total_amount: Decimal
    currency: str = "GBP"


class GRLineItem(BaseModel):
    description: str
    quantity_received: Decimal


class GoodsReceipt(BaseModel):
    gr_number: str
    po_number: str
    receipt_date: date
    line_items: list[GRLineItem]
    receiver: str
    notes: str = ""  # free text; may contain partial-delivery info (LLM-interpreted)


# ---------------------------------------------------------------------------
# Taxonomy and decisions (PRD §2.2, D-01, D-05)
# ---------------------------------------------------------------------------


class ExceptionCode(str, Enum):
    CLEAN = "clean"
    E01 = "E01"  # Amount mismatch (within tolerance)
    E02 = "E02"  # Amount mismatch (over tolerance)
    E03 = "E03"  # Quantity variance
    E04 = "E04"  # Duplicate invoice
    E05 = "E05"  # Missing PO reference
    E06 = "E06"  # PO already closed
    E07 = "E07"  # Tax calculation error
    E08 = "E08"  # Supplier name mismatch


class Action(str, Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT = "auto_reject"
    ESCALATE = "escalate"


class ConfidenceBand(str, Enum):
    GREEN = "green"  # > 90%
    AMBER = "amber"  # 70-90%
    RED = "red"  # < 70%


class OverrideReason(str, Enum):
    """D-05: structured override reason codes. Extend as override data reveals new patterns."""

    WRONG_PO = "agent_misidentified_po"
    CONTRACTUAL_ADJUSTMENT = "amount_difference_is_contractual_adjustment"
    NOT_DUPLICATE = "not_actually_a_duplicate"
    WRONG_CATEGORY = "wrong_exception_category"
    PARTIAL_DELIVERY_CONFIRMED = "partial_delivery_confirmed_offline"
    SUPPLIER_NAME_VARIANT_OK = "supplier_name_variant_acceptable"
    EXTRACTION_ERROR = "extraction_error"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Pipeline step outputs (PRD §3.1)
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Step 1."""

    invoice: Invoice | None
    confidence: float = Field(ge=0, le=1)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)  # e.g. arithmetic inconsistencies in the extracted document
    method: str = "structured"  # "structured" (JSON input) | "llm"
    needs_manual_entry: bool = False


class POCandidate(BaseModel):
    po_number: str
    score: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    """Step 2."""

    matched_po: PurchaseOrder | None
    method: str  # "exact" | "fuzzy" | "none"
    score: float = Field(ge=0, le=1)
    candidates: list[POCandidate] = Field(default_factory=list)


class Discrepancy(BaseModel):
    """Step 3: one field-level finding."""

    check: str  # "amount" | "quantity" | "gr_notes" | "line_items" | "tax" | "supplier_name" | "po_status" | "duplicate" | "po_reference"
    field: str
    invoice_value: str | None = None
    reference_value: str | None = None
    detail: str
    suggested_code: ExceptionCode
    confidence: float = Field(default=0.95, ge=0, le=1)  # strength of the evidence for this finding


class ValidationResult(BaseModel):
    """Step 3."""

    discrepancies: list[Discrepancy] = Field(default_factory=list)
    checks_performed: list[str] = Field(default_factory=list)
    goods_receipt: GoodsReceipt | None = None


class Classification(BaseModel):
    """Step 4. code is None when the agent could not classify (e.g. extraction failed)."""

    code: ExceptionCode | None
    confidence: float = Field(ge=0, le=1)  # calibrated, not raw model probability (D-04)
    raw_confidence: float | None = None  # pre-calibration score, kept for audit and for refitting
    band: ConfidenceBand
    action: Action
    rationale: str
    used_llm: bool = False


class EscalationBrief(BaseModel):
    """Step 5 / PRD §7.2."""

    summary: str
    what_i_found: list[str]
    what_i_checked: list[str]
    what_i_could_not_resolve: str
    recommended_action: str
    evidence: list[str]  # document references: invoice, PO, GR


class LLMCall(BaseModel):
    step: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False  # True in demo/replay mode
    latency_ms: int = 0
    attempts: int = 1  # > 1 means the call was retried, so its latency includes backoff waiting
    error: str | None = None  # set when the call failed and a rule-based fallback was used


class InvoiceResult(BaseModel):
    """Step 5 output and the audit-trail record for one invoice (US-05)."""

    doc_id: str | None = None
    invoice_number: str | None
    processed_at: datetime
    mode: str
    extraction: ExtractionResult
    match: MatchResult | None = None
    validation: ValidationResult | None = None
    classification: Classification
    brief: EscalationBrief | None = None
    llm_calls: list[LLMCall] = Field(default_factory=list)
    latency_ms: int = 0


class Decision(str, Enum):
    """An analyst's final call on an invoice (the agent recommends; humans decide on escalations)."""

    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"


class Review(BaseModel):
    """US-03 / D-05: an analyst's decision on one invoice, captured for the feedback loop.

    is_override is True when the analyst changed the agent's classification or reversed an
    autonomous decision. Confirming an escalation (e.g. approving an E02 after checking with
    the budget holder) is a review but not an override.
    """

    doc_id: str
    invoice_number: str | None
    original_code: ExceptionCode | None
    original_action: Action
    new_code: ExceptionCode | None
    decision: Decision
    is_override: bool
    reason: OverrideReason | None = None
    note: str | None = None
    analyst: str
    created_at: datetime
