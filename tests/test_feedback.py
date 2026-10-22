from datetime import datetime, timezone

from app.config import Settings
from app.feedback import analyse, wilson_upper
from app.models import (
    Action, Classification, ConfidenceBand, Decision, ExceptionCode as EC, ExtractionResult, InvoiceResult,
    OverrideReason, Review,
)

S = Settings()


def result(doc_id: str, code: EC, action: Action) -> InvoiceResult:
    return InvoiceResult(
        doc_id=doc_id, invoice_number=doc_id, processed_at=datetime.now(timezone.utc), mode="offline",
        extraction=ExtractionResult(invoice=None, confidence=1.0),
        classification=Classification(code=code, confidence=0.95, band=ConfidenceBand.GREEN, action=action,
                                      rationale="x"),
    )


def review(doc_id: str, code: EC, action: Action, *, override: bool, decision: Decision = Decision.APPROVE) -> Review:
    return Review(
        doc_id=doc_id, invoice_number=doc_id, original_code=code, original_action=action,
        new_code=EC.CLEAN if override else code, decision=decision, is_override=override,
        reason=OverrideReason.WRONG_CATEGORY if override else None, analyst="A",
        created_at=datetime.now(timezone.utc),
    )


def scenario(code: EC, action: Action, n: int, overrides: int, decision: Decision = Decision.APPROVE):
    """n reviews of one category, the first `overrides` of which disagree with the agent.

    `decision` applies to those disagreeing reviews only — on an auto-approved category, a reject is
    what makes an override a *reversal*.
    """
    results, reviews = {}, {}
    for i in range(n):
        doc = f"{code.value}-{i}"
        disagrees = i < overrides
        results[doc] = result(doc, code, action)
        reviews[doc] = review(doc, code, action, override=disagrees,
                              decision=decision if disagrees else Decision.APPROVE)
    return results, reviews


def category(report, code: EC):
    return next(c for c in report.categories if c.code == code)


def test_small_samples_cannot_move_the_boundary():
    """Three lucky reviews must not look like evidence."""
    report = analyse(*scenario(EC.E03, Action.ESCALATE, 3, 0), S)
    c = category(report, EC.E03)
    assert c.recommendation == "insufficient_evidence" and report.actionable == []


def test_a_clean_record_over_enough_reviews_recommends_widening():
    report = analyse(*scenario(EC.E03, Action.ESCALATE, 60, 3), S)
    c = category(report, EC.E03)
    assert c.recommendation == "widen" and c.override_rate == 0.05
    assert c.override_rate_upper is not None and c.override_rate_upper <= S.feedback_widen_max_override
    assert report.actionable and "E03" in report.actionable[0]


def test_the_same_rate_on_a_thinner_sample_does_not():
    """5% of 40 is the same rate as 5% of 60, but the bound is wider — so it holds."""
    report = analyse(*scenario(EC.E03, Action.ESCALATE, 40, 2), S)
    assert category(report, EC.E03).recommendation == "hold"


def test_reversed_autonomous_decisions_recommend_narrowing():
    # Analysts rejecting invoices the agent approved on its own: the loudest signal there is.
    results, reviews = scenario(EC.E01, Action.AUTO_APPROVE, 40, 4, decision=Decision.REJECT)
    report = analyse(results, reviews, S)
    c = category(report, EC.E01)
    assert c.recommendation == "narrow" and c.reversals == 4
    assert any("Stop letting the agent resolve E01" in a for a in report.actionable)


def test_some_categories_are_never_promoted_however_good_the_evidence():
    """E02 is 'pay more than the PO authorises'. A low override rate says the agent reads it right,
    not that a machine should approve it."""
    report = analyse(*scenario(EC.E02, Action.ESCALATE, 200, 2), S)
    c = category(report, EC.E02)
    assert c.recommendation == "hold" and not c.eligible
    assert "authority rather than accuracy" in c.reason
    assert report.actionable == []


def test_a_high_override_rate_blocks_widening():
    """E07 *is* eligible for autonomy, so here the override rate is what holds it back."""
    report = analyse(*scenario(EC.E07, Action.ESCALATE, 40, 16), S)
    c = category(report, EC.E07)
    assert c.recommendation == "hold" and c.eligible and c.override_rate == 0.4
    assert "Too unreliable" in c.reason


def test_an_ineligible_category_is_not_flattered_when_it_is_also_unreliable():
    c = category(analyse(*scenario(EC.E05, Action.ESCALATE, 40, 16), S), EC.E05)
    assert c.recommendation == "hold" and "reads this category reliably" not in c.reason
    assert "authority rather than accuracy anyway" in c.reason


def test_recommendations_never_apply_themselves():
    """The report is advice. Autonomy only moves when a person moves it."""
    before = frozenset(S.auto_resolvable)
    report = analyse(*scenario(EC.E03, Action.ESCALATE, 60, 0), S)
    assert category(report, EC.E03).recommendation == "widen"
    assert S.auto_resolvable == before


def test_wilson_bound_shrinks_with_evidence():
    assert wilson_upper(0, 5) > wilson_upper(0, 20) > wilson_upper(0, 100)
    assert wilson_upper(0, 40) < 0.15 < wilson_upper(2, 40)
