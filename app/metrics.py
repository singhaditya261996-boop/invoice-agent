"""Batch-level product metrics (PRD §1.6, US-04). Shared by the dashboard API and the evaluation runner."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from pydantic import BaseModel

from app.config import Settings
from app.models import Action, Decision, ExceptionCode, InvoiceResult, LLMCall, Review


class SupplierExceptions(BaseModel):
    supplier: str
    invoices: int
    exceptions: int
    codes: dict[str, int]


class LLMUsage(BaseModel):
    calls: int = 0
    cached_calls: int = 0
    failed_calls: int = 0  # rule-based fallback used instead
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_gbp: float = 0.0
    cost_per_invoice_gbp: float = 0.0


class Dashboard(BaseModel):
    invoices: int
    by_code: dict[str, int]
    by_action: dict[str, int]
    by_band: dict[str, int]
    exceptions: int  # classified as anything other than clean
    auto_resolved_exceptions: int
    auto_resolution_rate: float  # PRD target 40-60% of exceptions
    straight_through_rate: float  # all invoices decided without a human
    pending_review: int
    reviewed: int
    overrides: int
    override_rate: float  # PRD target < 15%: classifications changed by an analyst
    reversed_autonomous_decisions: int  # auto-approvals/rejections an analyst undid
    override_reasons: dict[str, int]
    top_suppliers: list[SupplierExceptions]
    median_latency_ms: int
    llm: LLMUsage


def reverses_autonomous_decision(review: Review) -> bool:
    """An analyst undid something the agent did on its own (the false-approval signal, PRD §1.6)."""
    return (review.original_action == Action.AUTO_APPROVE and review.decision != Decision.APPROVE) or \
        (review.original_action == Action.AUTO_REJECT and review.decision != Decision.REJECT)


def _code(r: InvoiceResult) -> str:
    return r.classification.code.value if r.classification.code else "unclassified"


def _supplier(r: InvoiceResult) -> str:
    if r.match and r.match.matched_po:
        return r.match.matched_po.supplier_name
    if r.extraction.invoice:
        return r.extraction.invoice.supplier_name
    return "unknown"


def llm_usage(calls: list[LLMCall], invoices: int, settings: Settings) -> LLMUsage:
    usage = LLMUsage()
    for c in calls:
        usage.calls += 1
        usage.cached_calls += c.cached
        usage.failed_calls += c.error is not None
        if c.cached:
            continue  # replayed responses cost nothing
        usage.input_tokens += c.input_tokens
        usage.output_tokens += c.output_tokens
        price_in, price_out = settings.llm_prices_usd_per_mtok.get(c.model, (0.0, 0.0))
        usage.cost_usd += (c.input_tokens * price_in + c.output_tokens * price_out) / 1_000_000
    usage.cost_gbp = usage.cost_usd * settings.gbp_per_usd
    usage.cost_per_invoice_gbp = usage.cost_gbp / invoices if invoices else 0.0
    return usage


def summarize(results: list[InvoiceResult], reviews: dict[str, Review], settings: Settings,
              top_n: int = 5) -> Dashboard:
    n = len(results)
    exceptions = [r for r in results if r.classification.code not in (ExceptionCode.CLEAN, None)]
    exception_ids = {id(r) for r in exceptions}
    auto_resolved = [r for r in exceptions if r.classification.action != Action.ESCALATE]
    autonomous = [r for r in results if r.classification.action != Action.ESCALATE]
    overrides = [rv for rv in reviews.values() if rv.is_override]

    per_supplier: dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for r in results:
        totals[_supplier(r)] += 1
        if id(r) in exception_ids:
            per_supplier[_supplier(r)][_code(r)] += 1
    top = sorted(per_supplier.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:top_n]

    return Dashboard(
        invoices=n,
        by_code=dict(sorted(Counter(_code(r) for r in results).items())),
        by_action=dict(sorted(Counter(r.classification.action.value for r in results).items())),
        by_band=dict(sorted(Counter(r.classification.band.value for r in results).items())),
        exceptions=len(exceptions),
        auto_resolved_exceptions=len(auto_resolved),
        auto_resolution_rate=len(auto_resolved) / len(exceptions) if exceptions else 0.0,
        straight_through_rate=len(autonomous) / n if n else 0.0,
        pending_review=sum(r.classification.action == Action.ESCALATE and r.doc_id not in reviews for r in results),
        reviewed=len(reviews),
        overrides=len(overrides),
        override_rate=len(overrides) / n if n else 0.0,
        reversed_autonomous_decisions=sum(reverses_autonomous_decision(rv) for rv in reviews.values()),
        override_reasons=dict(Counter(rv.reason.value for rv in overrides if rv.reason)),
        top_suppliers=[SupplierExceptions(supplier=s, invoices=totals[s], exceptions=sum(c.values()), codes=dict(c))
                       for s, c in top],
        median_latency_ms=int(median(r.latency_ms for r in results)) if results else 0,
        llm=llm_usage([c for r in results for c in r.llm_calls], n, settings),
    )
