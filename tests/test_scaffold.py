from decimal import Decimal

from fastapi.testclient import TestClient

from app.agent.classifier import apply_autonomy_rules, confidence_band
from app.api.main import app
from app.config import Settings
from app.models import Action, ConfidenceBand, ExceptionCode
from data.generator.generate import DISTRIBUTION


def test_tolerance_is_smaller_of_pct_and_absolute():
    s = Settings()
    assert s.default_tolerance.limit_for(Decimal("200")) == Decimal("2.00")
    assert s.default_tolerance.limit_for(Decimal("500000")) == Decimal("50.00")


def test_autonomy_boundary():
    s = Settings()
    assert apply_autonomy_rules(ExceptionCode.E01, 0.96, s) == Action.AUTO_APPROVE
    assert apply_autonomy_rules(ExceptionCode.E01, 0.94, s) == Action.ESCALATE
    assert apply_autonomy_rules(ExceptionCode.E04, 0.86, s) == Action.AUTO_REJECT
    assert apply_autonomy_rules(ExceptionCode.E04, 0.80, s) == Action.ESCALATE
    for code in ("E02", "E03", "E05", "E06", "E07", "E08"):
        assert apply_autonomy_rules(ExceptionCode(code), 0.99, s) == Action.ESCALATE


def test_confidence_bands():
    s = Settings()
    assert confidence_band(0.95, s) == ConfidenceBand.GREEN
    assert confidence_band(0.80, s) == ConfidenceBand.AMBER
    assert confidence_band(0.50, s) == ConfidenceBand.RED


def test_distribution_totals_500():
    assert sum(DISTRIBUTION.values()) == 500


def test_health():
    assert TestClient(app).get("/health").json()["status"] == "ok"
