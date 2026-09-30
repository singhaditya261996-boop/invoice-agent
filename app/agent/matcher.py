"""Step 2: Match (deterministic). Invoice -> PO, or 'no match' with candidate list.

1. Exact match on po_reference (formatting-insensitive).
2. Else fuzzy: supplier_name + total within 10% + ordered within 90 days, ranked by composite score.
A fuzzy match is accepted only if it scores at least min_match_score and clearly beats the
runner-up; otherwise the candidates are surfaced for the analyst (failure taxonomy: false match).
"""

from __future__ import annotations

from datetime import timedelta

from app.agent.tools import DataStore, lookup_po, search_pos
from app.config import Settings
from app.models import Invoice, MatchResult

MAX_CANDIDATES = 5


def match_invoice(invoice: Invoice, store: DataStore, settings: Settings) -> MatchResult:
    po = lookup_po(store, invoice.po_reference)
    if po:
        exact = po.po_number == (invoice.po_reference or "").strip()
        return MatchResult(matched_po=po, method="exact" if exact else "exact_normalized",
                           score=1.0 if exact else 0.99)

    window = invoice.subtotal * settings.fuzzy_amount_window_pct
    candidates = search_pos(
        store,
        invoice.supplier_name,
        amount_range=(invoice.subtotal - window, invoice.subtotal + window),
        date_range=(invoice.invoice_date - timedelta(days=settings.fuzzy_date_window_days), invoice.invoice_date),
        descriptions=[l.description for l in invoice.line_items],
    )[:MAX_CANDIDATES]
    if not candidates:
        return MatchResult(matched_po=None, method="none", score=0.0)

    best = candidates[0]
    margin = best.score - candidates[1].score if len(candidates) > 1 else 1.0
    if best.score >= settings.min_match_score and margin >= settings.min_match_margin:
        return MatchResult(matched_po=store.pos[best.po_number], method="fuzzy", score=best.score,
                           candidates=candidates)
    return MatchResult(matched_po=None, method="none", score=best.score, candidates=candidates)
