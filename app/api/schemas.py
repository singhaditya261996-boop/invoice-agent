"""Request and response bodies for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.config import RunMode
from app.models import (
    Action,
    ConfidenceBand,
    Decision,
    ExceptionCode,
    GoodsReceipt,
    Invoice,
    InvoiceResult,
    OverrideReason,
    PurchaseOrder,
    Review,
)


class InvoiceInput(BaseModel):
    """One invoice: either already structured, or the raw document text for LLM extraction."""

    doc_id: str | None = None
    invoice: Invoice | None = None
    document: str | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> InvoiceInput:
        if (self.invoice is None) == (self.document is None):
            raise ValueError("provide exactly one of 'invoice' or 'document'")
        return self


class BatchCreate(BaseModel):
    name: str | None = None
    mode: RunMode | None = None  # defaults to the server's configured mode
    purchase_orders: list[PurchaseOrder]
    goods_receipts: list[GoodsReceipt] = Field(default_factory=list)
    invoices: list[InvoiceInput] = Field(default_factory=list)


class DemoBatchCreate(BaseModel):
    mode: RunMode | None = None
    input: Literal["structured", "documents"] = "structured"  # documents require an LLM (live or demo fixtures)
    limit: int | None = Field(default=None, ge=1)


class BatchSummary(BaseModel):
    id: str
    name: str
    mode: RunMode
    status: str
    created_at: datetime
    total: int
    processed: int
    failed: int
    escalated: int
    pending_review: int


class ResultRow(BaseModel):
    """Compact row for the review queue."""

    doc_id: str
    invoice_number: str | None
    supplier_name: str | None
    total_amount: Decimal | None
    po_number: str | None
    match_method: str | None
    code: ExceptionCode | None
    action: Action
    confidence: float
    band: ConfidenceBand
    summary: str
    review: Decision | None
    is_override: bool


class ResultDetail(BaseModel):
    result: InvoiceResult
    review: Review | None


class ReviewCreate(BaseModel):
    decision: Decision
    new_code: ExceptionCode | None = None  # omit to keep the agent's classification
    reason: OverrideReason | None = None  # required when this overrides the agent (D-05)
    note: str | None = None
    analyst: str = Field(min_length=1)


class AuditRecord(BaseModel):
    """US-05: one line of the audit trail."""

    batch_id: str
    doc_id: str
    invoice_number: str | None
    supplier_name: str | None
    total_amount: str | None
    processed_at: datetime
    mode: str
    po_number: str | None
    match_method: str | None
    match_score: float | None
    code: str | None
    action: str
    confidence: float
    band: str
    rationale: str
    discrepancies: str
    llm_calls: int
    review_decision: str | None
    reviewed_by: str | None
    review_reason: str | None
    is_override: bool


# --------------------------------------------------------------------------- policy sandbox


class PolicyOverrides(BaseModel):
    """Thresholds to try. Anything omitted keeps the batch's configured value."""

    tolerance_pct: Decimal | None = Field(default=None, ge=0, le=1)
    tolerance_absolute: Decimal | None = Field(default=None, ge=0)
    auto_approve_confidence: float | None = Field(default=None, ge=0, le=1)
    auto_reject_duplicate_confidence: float | None = Field(default=None, ge=0, le=1)
    auto_resolvable: list[ExceptionCode] | None = None


class PolicyOutcome(BaseModel):
    by_action: dict[str, int]
    auto_resolution_rate: float
    straight_through_rate: float


class PolicyChange(BaseModel):
    doc_id: str
    invoice_number: str | None
    supplier_name: str | None
    total_amount: Decimal | None
    before_code: ExceptionCode | None
    before_action: Action
    after_code: ExceptionCode | None
    after_action: Action
    after_confidence: float


class PolicySimulation(BaseModel):
    """What this batch would have looked like under different rules (US-04, D-01, D-02)."""

    applied: dict[str, str]
    llm: str  # "replayed" (recorded responses) or "rules" (no model)
    before: PolicyOutcome
    after: PolicyOutcome
    changed: list[PolicyChange]
    newly_autonomous: int  # escalations the agent would now settle alone
    newly_escalated: int  # decisions it would now hand back to a human
    risk: list[str]
