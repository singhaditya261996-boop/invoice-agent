"""Agent configuration: tolerances, confidence thresholds, and autonomy rules.

Every value here traces to a decision in docs/decision-log.md. Change them there first.
"""

from __future__ import annotations

import os
from pathlib import Path
from decimal import Decimal
from enum import Enum

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.models import ExceptionCode


class RunMode(str, Enum):
    DEMO = "demo"  # cached LLM responses from data/fixtures (PRD §3.4)
    LIVE = "live"  # real Claude API calls
    OFFLINE = "offline"  # no LLM: rule-based fallbacks only (tests, deterministic baseline)


class ToleranceConfig(BaseModel):
    """D-02: default is 1% or GBP 50, whichever is smaller. Overridable per supplier / cost centre."""

    pct: Decimal = Decimal("0.01")
    absolute: Decimal = Decimal("50.00")

    def limit_for(self, po_total: Decimal) -> Decimal:
        return min(po_total * self.pct, self.absolute)


class Settings(BaseModel):
    mode: RunMode = RunMode.DEMO
    llm_provider: str = "anthropic"  # "anthropic" (the model this product would ship with) or "google"
    llm_model: str = "claude-opus-5"
    google_model: str = "gemini-2.5-flash"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max; tune against eval (Step 5)
    llm_max_tokens: int = 16000
    record_fixtures: bool = False  # live mode: also write responses to the demo-mode fixture store
    fixtures_path: Path = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "llm_responses.json"

    # D-02 tolerances
    default_tolerance: ToleranceConfig = Field(default_factory=ToleranceConfig)
    supplier_tolerances: dict[str, ToleranceConfig] = Field(default_factory=dict)  # keyed by supplier_id
    cost_centre_tolerances: dict[str, ToleranceConfig] = Field(default_factory=dict)

    # D-06: asymmetric thresholds
    auto_approve_confidence: float = 0.95
    auto_reject_duplicate_confidence: float = 0.85

    # D-01: only these exception types may be auto-resolved in MVP
    auto_resolvable: frozenset[ExceptionCode] = frozenset({ExceptionCode.E01, ExceptionCode.E04})

    # Failure taxonomy: "False match" mitigation
    min_match_score: float = 0.95
    min_match_margin: float = 0.05  # best fuzzy candidate must beat the runner-up by this much

    # PRD §3.1 Step 2 fuzzy-match window
    fuzzy_amount_window_pct: Decimal = Decimal("0.10")
    fuzzy_date_window_days: int = 90

    # PRD §3.1 Step 1 fallback. Threshold value not specified in PRD — assumption, revisit after eval.
    min_extraction_confidence: float = 0.90

    # Duplicate detection window (PRD §2.3: same or ±1 day)
    duplicate_date_window_days: int = 1

    # UK VAT (PRD §2.3)
    vat_rate: Decimal = Decimal("0.20")
    # Per-line rounding can differ from rounding on the subtotal by a few pence.
    tax_rounding_tolerance: Decimal = Decimal("0.05")

    # Without a goods receipt the three-way match is incomplete (US-06: flag uncertainty)
    missing_gr_confidence_factor: float = 0.85
    # Several discrepancies on one invoice: root cause is a judgement call
    overlapping_confidence_factor: float = 0.85

    # Cost reporting. USD list prices per million tokens (input, output); GBP rate is an assumption.
    llm_prices_usd_per_mtok: dict[str, tuple[float, float]] = Field(default_factory=lambda: {
        "claude-opus-5": (5.0, 25.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-sonnet-5": (2.0, 10.0),
        "claude-haiku-4-5": (1.0, 5.0),
    })
    gbp_per_usd: float = 0.79

    @property
    def model_name(self) -> str:
        return self.google_model if self.llm_provider == "google" else self.llm_model

    # API
    review_log_path: Path = Path(__file__).resolve().parents[1] / "var" / "reviews.jsonl"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # Trust design §7.1 confidence bands
    band_green_min: float = 0.90
    band_amber_min: float = 0.70

    def tolerance_for(self, supplier_id: str | None, cost_centre: str | None) -> ToleranceConfig:
        """Supplier override beats cost-centre override beats default."""
        if supplier_id and supplier_id in self.supplier_tolerances:
            return self.supplier_tolerances[supplier_id]
        if cost_centre and cost_centre in self.cost_centre_tolerances:
            return self.cost_centre_tolerances[cost_centre]
        return self.default_tolerance


def load_settings() -> Settings:
    """Settings from the environment, loading a local .env first (never committed)."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    provider = os.getenv("INVOICE_AGENT_PROVIDER", "anthropic")
    model = os.getenv("INVOICE_AGENT_MODEL")  # demo mode must name the model whose responses were recorded
    return Settings(
        mode=RunMode(os.getenv("INVOICE_AGENT_MODE", RunMode.DEMO.value)),
        llm_provider=provider,
        **({"google_model" if provider == "google" else "llm_model": model} if model else {}),
    )
