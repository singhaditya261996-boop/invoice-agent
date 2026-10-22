"""The feedback loop: what analyst overrides say about where autonomy should sit.

D-01 says the autonomy boundary "should widen over time based on measured override rates per
exception type". This is the measurement, and the recommendation that follows from it.

Two deliberate properties:

1. **It recommends; it never applies.** Widening autonomy is a decision a person takes, with the
   policy sandbox to quantify it. An agent that quietly expanded its own authority on the strength
   of its own metrics is the failure this product exists to avoid.
2. **Small samples cannot trigger a change.** A category needs a minimum number of reviews, and the
   test uses the upper bound of the override rate rather than the rate itself, so three lucky
   reviews never look like evidence.
"""

from __future__ import annotations

from math import sqrt

from pydantic import BaseModel

from app.config import Settings
from app.metrics import reverses_autonomous_decision
from app.models import ExceptionCode, InvoiceResult, Review

Z = 1.96  # 95% confidence


def wilson_upper(successes: int, trials: int, z: float = Z) -> float:
    """Upper bound of the true rate given an observed one. Wide for small samples, which is the point."""
    if trials == 0:
        return 1.0
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = p + z**2 / (2 * trials)
    margin = z * sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2))
    return min(1.0, (centre + margin) / denominator)


class CategoryEvidence(BaseModel):
    code: ExceptionCode
    autonomous_today: bool
    eligible: bool  # may this category ever be resolved without a human, whatever the evidence?
    reviewed: int
    overrides: int
    override_rate: float | None
    override_rate_upper: float | None  # 95% upper bound; what the recommendation actually tests
    reversals: int  # autonomous decisions an analyst undid
    recommendation: str  # "widen" | "narrow" | "hold" | "insufficient_evidence"
    reason: str
    top_override_reason: str | None


class FeedbackReport(BaseModel):
    note: str | None = None  # set when the review history is not this batch's own (e.g. the demo)
    reviews: int
    min_reviews_required: int
    categories: list[CategoryEvidence]
    actionable: list[str]  # the recommendations worth a manager's attention, in plain English


def _code_of(result: InvoiceResult) -> ExceptionCode | None:
    return result.classification.code


def analyse(results: dict[str, InvoiceResult], reviews: dict[str, Review], settings: Settings) -> FeedbackReport:
    by_code: dict[ExceptionCode, list[Review]] = {}
    for doc_id, review in reviews.items():
        code = _code_of(results[doc_id]) if doc_id in results else review.original_code
        if code is not None:
            by_code.setdefault(code, []).append(review)

    categories: list[CategoryEvidence] = []
    for code in sorted(ExceptionCode, key=lambda c: c.value):
        items = by_code.get(code, [])
        autonomous = code in settings.auto_resolvable or code == ExceptionCode.CLEAN
        eligible = autonomous or code in settings.eligible_for_autonomy
        overrides = [r for r in items if r.is_override]
        reversals = [r for r in items if reverses_autonomous_decision(r)]
        rate = len(overrides) / len(items) if items else None
        upper = wilson_upper(len(overrides), len(items)) if items else None

        if items and not eligible:
            # No amount of evidence promotes these: see Settings.eligible_for_autonomy (D-16).
            recommendation = "hold"
            reliable = rate is not None and rate <= settings.feedback_widen_max_override
            reason = (f"Override rate {rate:.0%} over {len(items)} reviews. "
                      + ("The agent reads this category reliably, but resolving it is a question of "
                         "authority rather than accuracy" if reliable
                         else "Resolving it is a question of authority rather than accuracy anyway")
                      + ", so it stays with a human whatever the evidence says.")
        elif len(items) < settings.feedback_min_reviews:
            recommendation = "insufficient_evidence"
            reason = (f"{len(items)} review(s); {settings.feedback_min_reviews} needed before this "
                      "category can move either way.")
        elif not autonomous and upper is not None and upper <= settings.feedback_widen_max_override:
            recommendation = "widen"
            reason = (f"Analysts changed the agent's call on {rate:.0%} of {len(items)} reviews — at most "
                      f"{upper:.0%} allowing for the sample size, so we are 95% confident this category "
                      f"sits under the {settings.feedback_widen_max_override:.0%} override target. Every "
                      "one of these still costs an analyst their time.")
        elif autonomous and reversals and len(reversals) / len(items) >= settings.feedback_narrow_min_reversal:
            recommendation = "narrow"
            reason = (f"Analysts reversed {len(reversals)} of {len(items)} decisions the agent made on "
                      "its own. It should hand these back until that stops.")
        elif rate is not None and rate >= settings.feedback_narrow_min_override:
            recommendation = "narrow" if autonomous else "hold"
            reason = (f"Analysts changed the agent's call on {rate:.0%} of {len(items)} reviews. "
                      + ("Autonomy here is not earning its keep." if autonomous
                         else "Too unreliable to consider widening."))
        else:
            recommendation = "hold"
            reason = (f"Override rate {rate:.0%} over {len(items)} reviews — "
                      + ("working as intended." if autonomous
                         else f"not yet at the {settings.feedback_widen_max_override:.0%} bar for widening."))

        reasons = [r.reason.value for r in overrides if r.reason]
        categories.append(CategoryEvidence(
            code=code, autonomous_today=autonomous, eligible=eligible, reviewed=len(items),
            overrides=len(overrides),
            override_rate=round(rate, 4) if rate is not None else None,
            override_rate_upper=round(upper, 4) if upper is not None else None,
            reversals=len(reversals), recommendation=recommendation, reason=reason,
            top_override_reason=max(set(reasons), key=reasons.count) if reasons else None,
        ))

    actionable = [
        (f"Let the agent resolve {c.code.value} on its own" if c.recommendation == "widen"
         else f"Stop letting the agent resolve {c.code.value} on its own") + f" — {c.reason}"
        for c in categories if c.recommendation in ("widen", "narrow")
    ]
    return FeedbackReport(reviews=len(reviews), min_reviews_required=settings.feedback_min_reviews,
                          categories=categories, actionable=actionable)
