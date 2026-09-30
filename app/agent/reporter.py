"""Step 5: Report. Escalation brief for anything not auto-approved (PRD §7.2).

The factual sections (what I found, what I checked, evidence) are always filled from a
template, so every number shown to the analyst comes from deterministic checks. The LLM only
writes the three narrative sections (summary, what I could not resolve, recommended action)
from those facts. Without an LLM, template wording is used.
"""

from __future__ import annotations

import json

from app.agent.classifier import TAXONOMY
from app.agent.llm import LLM
from app.config import Settings
from app.models import (
    Action,
    Classification,
    EscalationBrief,
    ExceptionCode as EC,
    ExtractionResult,
    Invoice,
    MatchResult,
    ValidationResult,
)

BRIEF_SYSTEM = """You write escalation briefs for accounts-payable analysts reviewing invoices that an \
automated agent could not resolve. Write in the first person as the agent. Use only the facts provided: \
never invent amounts, names, dates, or documents. State uncertainty plainly: say what you matched and why, \
rather than asserting it. Keep each field to one or two sentences. The summary is a single line naming the \
invoice, the supplier, and the problem with its key figure."""

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "what_i_could_not_resolve": {"type": "string"},
        "recommended_action": {"type": "string"},
    },
    "required": ["summary", "what_i_could_not_resolve", "recommended_action"],
    "additionalProperties": False,
}

UNRESOLVED = {
    EC.CLEAN: "Every check passed, but my confidence is below the auto-approval threshold.",
    EC.E01: "The amount difference is within tolerance, but my confidence is below the auto-approval threshold.",
    EC.E02: "The amount difference exceeds the tolerance threshold, so I cannot approve it.",
    EC.E03: "The quantity billed has not been confirmed as received.",
    EC.E04: "I rejected this as a duplicate of an invoice already processed.",
    EC.E05: "I cannot confirm which purchase order authorises this spend.",
    EC.E06: "The purchase order this invoice references is already closed.",
    EC.E07: "The VAT on the invoice does not match my recalculation.",
    EC.E08: "The invoicing entity does not match the supplier on the purchase order.",
}


def generate_escalation_brief(
    invoice: Invoice | None,
    extraction: ExtractionResult,
    match: MatchResult | None,
    validation: ValidationResult | None,
    classification: Classification,
    settings: Settings,
    llm: LLM | None = None,
) -> EscalationBrief | None:
    if classification.action == Action.AUTO_APPROVE:
        return None
    if invoice is None or extraction.needs_manual_entry:
        return _extraction_failure_brief(extraction)

    po = match.matched_po if match else None
    gr = validation.goods_receipt if validation else None
    found = [d.detail for d in validation.discrepancies] if validation else []
    checked = [_match_sentence(invoice, match, settings)] + (validation.checks_performed if validation else [])
    evidence = [f"Invoice {invoice.invoice_number}"]
    if po:
        evidence.append(f"PO {po.po_number}")
    if gr:
        evidence.append(f"Goods receipt {gr.gr_number}")
    evidence += [f"Candidate PO {c.po_number} (score {c.score:.2f})" for c in (match.candidates if match else [])
                 if not po or c.po_number != po.po_number]
    evidence += [f"Prior invoice {d.reference_value}" for d in (validation.discrepancies if validation else [])
                 if d.check == "duplicate"]

    code = classification.code
    brief = EscalationBrief(
        summary=f"Invoice {invoice.invoice_number} from {invoice.supplier_name}: "
                + (found[0] if found else f"confidence {classification.confidence:.0%} below threshold"),
        what_i_found=found or ["No discrepancies found."],
        what_i_checked=checked,
        what_i_could_not_resolve=_unresolved(classification),
        recommended_action=_recommendation(classification, invoice, match, validation),
        evidence=evidence,
    )

    if llm:
        facts = {
            "invoice": {"number": invoice.invoice_number, "supplier": invoice.supplier_name,
                        "date": str(invoice.invoice_date), "subtotal": str(invoice.subtotal),
                        "vat": str(invoice.tax_amount), "total": str(invoice.total_amount),
                        "po_reference": invoice.po_reference},
            "classification": {"code": code.value, "category": TAXONOMY.get(code, "clean"), "action": classification.action.value,
                               "confidence": classification.confidence, "rationale": classification.rationale},
            "purchase_order": ({"number": po.po_number, "supplier": po.supplier_name, "total": str(po.total_amount),
                                "status": po.status.value, "approver": po.approver} if po else None),
            "goods_receipt": ({"number": gr.gr_number, "receiver": gr.receiver, "notes": gr.notes} if gr else None),
            "what_i_found": brief.what_i_found,
            "what_i_checked": brief.what_i_checked,
            "template_recommendation": brief.recommended_action,
        }
        data = llm.json("brief", BRIEF_SYSTEM, json.dumps(facts, indent=2), BRIEF_SCHEMA)
        if data:
            brief = brief.model_copy(update=data)
    return brief


def _match_sentence(invoice: Invoice, match: MatchResult | None, settings: Settings) -> str:
    if match is None:
        return "PO matching not attempted"
    if match.method == "exact":
        return f"Matched to {match.matched_po.po_number} on the PO reference quoted on the invoice"
    if match.method == "exact_normalized":
        return (f"Matched to {match.matched_po.po_number}: the invoice quotes {invoice.po_reference!r}, "
                "the same number formatted differently")
    if match.method == "fuzzy":
        return (f"Matched to {match.matched_po.po_number} by supplier, amount and line items "
                f"(match score {match.score:.2f}); the invoice did not quote a valid PO reference")
    if match.candidates:
        return (f"No confident PO match: best candidate {match.candidates[0].po_number} scored "
                f"{match.candidates[0].score:.2f} (needs {settings.min_match_score:.2f} and a lead of "
                f"{settings.min_match_margin:.2f} over the next)")
    return (f"No PO found for this supplier within {settings.fuzzy_amount_window_pct:.0%} of the amount "
            f"and {settings.fuzzy_date_window_days} days of the invoice date")


def _unresolved(classification: Classification) -> str:
    text = UNRESOLVED[classification.code]
    if classification.code == EC.E04 and classification.action == Action.ESCALATE:
        text = "This looks like a duplicate, but the evidence is not strong enough to reject it automatically."
    return f"{text} Confidence {classification.confidence:.0%}."


def _recommendation(classification: Classification, invoice: Invoice, match: MatchResult | None,
                    validation: ValidationResult | None) -> str:
    code = classification.code
    po = match.matched_po if match else None
    gr = validation.goods_receipt if validation else None
    approver = po.approver if po else "the budget holder"
    receiver = gr.receiver if gr else "the receiving team"
    if code == EC.E02:
        return f"Confirm the price change with {approver} (PO approver) or request a credit note for the difference."
    if code == EC.E03:
        return (f"Confirm the quantity received with {receiver}. Pay only for goods received, and hold the "
                "balance until the remaining delivery is booked in.")
    if code == EC.E04 and classification.action == Action.ESCALATE:
        return "Compare with the prior invoice listed below; reject if it is the same charge, approve if it is a separate one."
    if code == EC.E04:
        return "No action needed unless the supplier disputes it; if they do, confirm this is a separate charge."
    if code == EC.E05:
        if po or (match and match.candidates):
            target = po.po_number if po else match.candidates[0].po_number
            return f"Confirm with the requester that {target} is the correct PO, then update the reference."
        return "Identify the budget holder and either raise a retrospective PO or reject as unauthorised spend."
    if code == EC.E06:
        return f"Check whether {po.po_number} was already fully invoiced; if so, reject this invoice or request a credit."
    if code == EC.E07:
        return "Request a corrected invoice with VAT at the standard rate before approving."
    if code == EC.E08:
        return ("Confirm the supplier's legal entity and bank details before paying; the invoicing company "
                "may be a different entity from the one on the PO.")
    return "Review the checks above and approve if satisfied."


def _extraction_failure_brief(extraction: ExtractionResult) -> EscalationBrief:
    inv = extraction.invoice
    name = f"Invoice {inv.invoice_number} from {inv.supplier_name}" if inv else "Invoice"
    found = [f"Could not read with certainty: {', '.join(extraction.missing_fields)}"] if extraction.missing_fields \
        else ([] if inv else ["Could not extract the document"])
    return EscalationBrief(
        summary=f"{name} could not be read reliably; manual data entry required",
        what_i_found=found + extraction.issues,
        what_i_checked=[f"Extraction confidence {extraction.confidence:.0%}"],
        what_i_could_not_resolve="I did not match or validate this invoice because the extracted data may be wrong.",
        recommended_action="Key the invoice manually, then resubmit it for matching.",
        evidence=["Source document"],
    )
