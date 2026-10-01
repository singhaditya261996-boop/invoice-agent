# Failure taxonomy

How the agent can fail, how likely and how bad that is, what stops it, and whether that has been
tested. Used in the [model card](model-card.md) and in analyst training material.

Status key: **Tested** — a test or evaluation run exercises it · **Mitigated** — a safeguard exists
but has not been exercised end to end · **Open** — accepted risk for the MVP.

## Original taxonomy (PRD §6)

| Failure | Severity | Likelihood | Example | Mitigation | Status |
|---|---|---|---|---|---|
| Extraction hallucination | High | Medium | £12,450 read as £124,500 from a poor scan | Arithmetic consistency checks on every extracted invoice (line totals, subtotal, VAT); low confidence goes to manual entry instead of matching | **Tested** — simulated misreads on up to 100% of invoices; 369 of 369 payment-affecting misreads caught |
| False match | High | Low | Invoice matched to the wrong PO because the supplier has several similar POs | A fuzzy match must score ≥ 0.95 *and* beat the runner-up by 0.05; otherwise candidates are shown and the invoice escalates | **Tested** — the 6 `ambiguous_candidates` invoices |
| False auto-approval | Critical | Low | An invoice that should have been escalated is approved | Conservative autonomy boundary (D-01); 95% threshold (D-06); rules applied after the model's answer, never by it | **Tested** — 0 false approvals across every evaluation run, including 100% misread |
| Duplicate false positive | Medium | Medium | A legitimate monthly retainer flagged as a duplicate | Duplicate evidence is weighted: a different PO lowers confidence below the auto-reject bar, so it escalates rather than rejects | **Tested** — the 10 `recurring_similar_invoice` invoices |
| Confidence miscalibration | Medium | Medium | "90% confident" is right only 70% of the time | Calibration measured every run; isotonic map fitted from results (D-04) | **Partly tested** — mechanism verified (0.4% cross-fitted); the real fit needs the live run |
| GR notes misinterpretation | Medium | Medium | "returned 5 units" misread, wrong quantity validated | Notes are cross-checked against structured GR quantities; a conflict escalates rather than resolving | **Tested** with rule-based reading (the 5 `gr_notes_only` invoices); model reading untested |
| Scope creep | Low | Low | The agent resolves an exception type it is not authorised to resolve | Autonomy rules run after classification; the model chooses only among findings that exist | **Tested** — `test_overlapping_discrepancies_use_llm_but_rules_decide_action`, `test_llm_root_cause_outside_findings_is_ignored` |
| Adversarial invoice | High | Low | An invoice crafted to exploit extraction or matching | Out of scope for the MVP | **Open** — stated as a limitation |

## Found during the build

These were not in the original taxonomy. All three came out of the evaluation, not the unit tests.

| Failure | Severity | How it happened | Mitigation | Status |
|---|---|---|---|---|
| **Double payment after manual entry** | Critical | The original invoice was misread and set aside for manual entry, so it was not in the duplicate-check history; the clean resubmission matched nothing and was auto-approved | Invoices awaiting manual entry are kept as *unverified*; any strong link to one escalates ([D-09](decision-log.md#d-09-invoices-awaiting-manual-entry-stay-in-the-duplicate-check-history)) | **Tested** — `test_resubmission_of_invoice_awaiting_manual_entry_is_not_approved` |
| **Double payment after a misread date** | Critical | A misread invoice date moved a duplicate outside the ±1-day window, and a renumbered duplicate then looked new | The same PO billed twice for the same amount is flagged on any date, and escalated ([D-10](decision-log.md#d-10-the-same-po-billed-twice-for-the-same-amount-is-a-duplicate-signal-on-any-date)) | **Tested** — simulated-misread runs at 30% and 100% |
| **Crash on a partly-readable invoice** | Medium | An invoice was extracted but scored below the confidence threshold, leaving no classification; the brief generator assumed either a classification or no invoice at all | Manual-entry briefs are produced from the extraction result, naming the invoice and the arithmetic that failed | **Tested** — `test_low_confidence_extraction_escalates_without_classifying` |

## Known weaknesses not yet mitigated

- **Supplier identity across a misread name.** Duplicate checks on unverified invoices match
  supplier names fuzzily (≥ 90% similarity). A badly misread supplier name plus a changed invoice
  number and amount would evade the check. Unlikely in combination, untested in the live model.
- **The model's reading of goods-receipt notes is untested.** Only the keyword fallback has been
  exercised. The fallback is deliberately trigger-happy (a note saying "nothing missing" reads as a
  shortfall and escalates), which is safe but noisy.
- **Cost and latency are projections.** No live run has been made, so the < 30 s and < £0.15 targets
  are unverified.
- **Live-model failure modes are now partly observed.** Throttling (429) and overloaded models (503)
  have both occurred against a real API. Throttling was already retried; 503 was not, so five calls
  fell through to rules and three invoices went to manual entry unnecessarily — found by a live run,
  fixed, and covered by `test_gemini_retries_transient_errors_then_succeeds`. Refusals, truncation
  and malformed structured output remain stub-tested only.
