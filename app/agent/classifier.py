"""Step 4: Classify. Discrepancies -> exception code, calibrated confidence, action.

Single clear discrepancy: deterministic mapping. Overlapping discrepancies: LLM
picks the root cause. Autonomy rules (D-01, D-06) are applied AFTER any LLM
recommendation and cannot be overridden by it (failure taxonomy: scope creep).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.agent.llm import LLM
from app.config import Settings
from app.models import (
    Action,
    Classification,
    ConfidenceBand,
    ExceptionCode as EC,
    ExtractionResult,
    MatchResult,
    ValidationResult,
)

# Root-cause precedence when discrepancies overlap and no LLM is available. A duplicate or a
# missing/closed PO invalidates everything downstream; a wrong supplier outranks amount detail.
PRIORITY = [EC.E04, EC.E05, EC.E06, EC.E08, EC.E02, EC.E03, EC.E07, EC.E01]

TAXONOMY = {
    EC.E01: "Amount mismatch within tolerance",
    EC.E02: "Amount mismatch over tolerance",
    EC.E03: "Quantity variance (partial or over delivery)",
    EC.E04: "Duplicate invoice",
    EC.E05: "Missing or invalid PO reference",
    EC.E06: "PO already closed",
    EC.E07: "Tax calculation error",
    EC.E08: "Supplier name mismatch",
}

ROOT_CAUSE_SYSTEM = """You are an accounts-payable exception analyst. An invoice failed three-way matching \
with several discrepancies. Decide which single exception category is the root cause: the one that, once \
resolved, best explains the others. Choose only from the categories present in the findings. Use only the \
facts given."""

CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "eval" / "results" / "calibration.json"


class Calibrator:
    """D-04: maps raw scores to calibrated probabilities via a piecewise-linear table.

    The table is fitted on the evaluation set (Step 5). Until then it is the identity.
    """

    def __init__(self, points: list[tuple[float, float]] | None = None) -> None:
        self.points = sorted(points or [(0.0, 0.0), (1.0, 1.0)])

    @classmethod
    def load(cls, path: Path = CALIBRATION_PATH) -> Calibrator:
        if path.exists():
            return cls([tuple(p) for p in json.loads(path.read_text())["points"]])
        return cls()

    def __call__(self, raw: float) -> float:
        pts = self.points
        if raw <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if raw <= x1:
                return y0 + (y1 - y0) * (raw - x0) / (x1 - x0) if x1 > x0 else y1
        return pts[-1][1]


def confidence_band(confidence: float, settings: Settings) -> ConfidenceBand:
    if confidence > settings.band_green_min:
        return ConfidenceBand.GREEN
    if confidence >= settings.band_amber_min:
        return ConfidenceBand.AMBER
    return ConfidenceBand.RED


def apply_autonomy_rules(code: EC, confidence: float, settings: Settings) -> Action:
    """Hard-coded guardrail. Anything uncertain or outside the autonomy boundary escalates."""
    if code != EC.CLEAN and code not in settings.auto_resolvable:
        return Action.ESCALATE
    if code == EC.E04:
        return Action.AUTO_REJECT if confidence >= settings.auto_reject_duplicate_confidence else Action.ESCALATE
    return Action.AUTO_APPROVE if confidence >= settings.auto_approve_confidence else Action.ESCALATE


def classify(
    extraction: ExtractionResult,
    match: MatchResult,
    validation: ValidationResult,
    settings: Settings,
    llm: LLM | None = None,
    calibrator: Calibrator | None = None,
) -> Classification:
    calibrator = calibrator or Calibrator()
    found = validation.discrepancies
    codes = sorted({d.suggested_code for d in found}, key=PRIORITY.index)
    # Match quality only matters when there is a PO to be wrong about.
    match_factor = match.score if match.matched_po else 1.0
    gr_factor = 1.0 if validation.goods_receipt or not match.matched_po else settings.missing_gr_confidence_factor
    used_llm = False

    if not codes:
        code = EC.CLEAN
        raw = match_factor * gr_factor * extraction.confidence
        rationale = f"All checks passed: {len(validation.checks_performed)} checks, no discrepancies."
        if gr_factor < 1:
            rationale += " No goods receipt on file, so the three-way match is incomplete."
    else:
        code, rationale, used_llm = _root_cause(codes, validation, llm)
        evidence = max(d.confidence for d in found if d.suggested_code == code)
        raw = evidence * match_factor * gr_factor * extraction.confidence
        if len(codes) > 1:
            raw *= settings.overlapping_confidence_factor
        if len(codes) == 1:
            n = sum(d.suggested_code == code for d in found)
            rationale = f"{TAXONOMY[code]}: {n} finding(s). " + "; ".join(
                d.detail for d in found if d.suggested_code == code)

    confidence = round(calibrator(raw), 4)
    return Classification(
        code=code,
        confidence=confidence,
        raw_confidence=round(raw, 4),
        band=confidence_band(confidence, settings),
        action=apply_autonomy_rules(code, confidence, settings),  # always last; the LLM cannot bypass it
        rationale=rationale,
        used_llm=used_llm,
    )


def _root_cause(codes: list[EC], validation: ValidationResult, llm: LLM | None) -> tuple[EC, str, bool]:
    fallback = codes[0]
    if len(codes) == 1:
        return fallback, "", False
    if llm:
        findings = "\n".join(f"- [{d.suggested_code.value} {TAXONOMY[d.suggested_code]}] {d.detail}"
                             for d in validation.discrepancies)
        schema = {
            "type": "object",
            "properties": {
                "root_cause": {"type": "string", "enum": [c.value for c in codes]},
                "explanation": {"type": "string"},
            },
            "required": ["root_cause", "explanation"],
            "additionalProperties": False,
        }
        data = llm.json("classify", ROOT_CAUSE_SYSTEM, f"Findings:\n{findings}", schema)
        if data and data.get("root_cause") in {c.value for c in codes}:
            return EC(data["root_cause"]), f"Overlapping discrepancies ({', '.join(c.value for c in codes)}). " \
                f"{data['explanation']}", True
    return fallback, (f"Overlapping discrepancies ({', '.join(c.value for c in codes)}); "
                      f"{fallback.value} takes precedence as root cause by rule."), False
