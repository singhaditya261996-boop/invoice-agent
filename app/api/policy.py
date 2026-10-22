"""Policy sandbox: what this batch would have looked like under different rules.

The autonomy boundary (D-01) and the tolerance rule (D-02) are product decisions with a real
trade-off: loosen them and more invoices settle without a human, but the agent acts on weaker
evidence. This re-runs a processed batch under different thresholds and reports the difference,
so the trade-off can be inspected rather than argued about.

It never calls a model. Recorded responses are replayed where they exist and the rule-based
fallbacks run where they do not, so exploring costs nothing and cannot change a live bill.
"""

from __future__ import annotations

from app.agent.llm import make_llm
from app.agent.pipeline import InvoiceAgent
from app.agent.tools import DataStore
from app.api.schemas import PolicyChange, PolicyOutcome, PolicyOverrides, PolicySimulation
from app.api.state import Batch
from app.config import RunMode, Settings, ToleranceConfig
from app.metrics import summarize
from app.models import Action, ExceptionCode, InvoiceResult

SAFE_TO_SETTLE = {ExceptionCode.CLEAN, ExceptionCode.E01, ExceptionCode.E04}


def _outcome(results: list[InvoiceResult], settings: Settings) -> PolicyOutcome:
    d = summarize(results, {}, settings)
    return PolicyOutcome(by_action=d.by_action, auto_resolution_rate=round(d.auto_resolution_rate, 4),
                         straight_through_rate=round(d.straight_through_rate, 4))


def _applied(settings: Settings) -> dict[str, str]:
    t = settings.default_tolerance
    return {
        "tolerance": f"{t.pct:.1%} or £{t.absolute}, whichever is smaller",
        "auto_approve_confidence": f"{settings.auto_approve_confidence:.0%}",
        "auto_reject_duplicate_confidence": f"{settings.auto_reject_duplicate_confidence:.0%}",
        "auto_resolvable": ", ".join(sorted(c.value for c in settings.auto_resolvable)) or "none",
    }


def simulate(batch: Batch, overrides: PolicyOverrides) -> PolicySimulation:
    base = batch.agent.settings
    tolerance = ToleranceConfig(
        pct=base.default_tolerance.pct if overrides.tolerance_pct is None else overrides.tolerance_pct,
        absolute=(base.default_tolerance.absolute if overrides.tolerance_absolute is None
                  else overrides.tolerance_absolute),
    )
    settings = base.model_copy(update={
        "default_tolerance": tolerance,
        "auto_approve_confidence": overrides.auto_approve_confidence if overrides.auto_approve_confidence
        is not None else base.auto_approve_confidence,
        "auto_reject_duplicate_confidence": overrides.auto_reject_duplicate_confidence
        if overrides.auto_reject_duplicate_confidence is not None else base.auto_reject_duplicate_confidence,
        "auto_resolvable": frozenset(overrides.auto_resolvable) if overrides.auto_resolvable is not None
        else base.auto_resolvable,
        # Live batches replay their recorded responses rather than spending on a hypothetical.
        "mode": RunMode.OFFLINE if base.mode == RunMode.OFFLINE else RunMode.DEMO,
    })

    store = DataStore(list(batch.agent.store.pos.values()), list(batch.agent.store.goods_receipts.values()))
    agent = InvoiceAgent(store, settings, make_llm(settings), batch.agent.calibrator)
    before = list(batch.results.values())
    after = [agent.process(batch.sources[doc_id].content, doc_id) for doc_id in batch.results]

    changed = []
    for was, now in zip(before, after):
        if (was.classification.code, was.classification.action) == (now.classification.code,
                                                                    now.classification.action):
            continue
        invoice = now.extraction.invoice or was.extraction.invoice
        changed.append(PolicyChange(
            doc_id=now.doc_id, invoice_number=now.invoice_number,
            supplier_name=invoice.supplier_name if invoice else None,
            total_amount=invoice.total_amount if invoice else None,
            before_code=was.classification.code, before_action=was.classification.action,
            after_code=now.classification.code, after_action=now.classification.action,
            after_confidence=now.classification.confidence,
        ))

    newly_autonomous = [c for c in changed if c.before_action == Action.ESCALATE
                        and c.after_action != Action.ESCALATE]
    newly_escalated = [c for c in changed if c.before_action != Action.ESCALATE
                       and c.after_action == Action.ESCALATE]

    risk: list[str] = []
    promoted = [c for c in newly_autonomous if c.before_code not in SAFE_TO_SETTLE]
    if promoted:
        codes = ", ".join(sorted({c.before_code.value for c in promoted if c.before_code}))
        risk.append(f"{len(promoted)} invoice(s) the agent escalated as {codes} would now be settled "
                    "without a human.")
    approved = [c for c in newly_autonomous if c.after_action == Action.AUTO_APPROVE]
    if approved:
        total = sum((c.total_amount or 0) for c in approved)
        risk.append(f"£{total:,.2f} across {len(approved)} invoice(s) would be approved for payment "
                    "that an analyst currently sees first.")
    if newly_escalated:
        risk.append(f"{len(newly_escalated)} invoice(s) the agent settles today would go back to the "
                    "review queue.")
    if not changed:
        risk.append("Nothing changes on this batch. The thresholds that moved are not the ones binding here.")

    return PolicySimulation(
        applied=_applied(settings),
        llm="rules" if settings.mode == RunMode.OFFLINE else "replayed",
        before=_outcome(before, base), after=_outcome(after, settings),
        changed=changed, newly_autonomous=len(newly_autonomous), newly_escalated=len(newly_escalated),
        risk=risk,
    )
