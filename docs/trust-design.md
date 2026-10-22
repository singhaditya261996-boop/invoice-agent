# Trust design

Trust calibration is the central UX challenge: analysts need to build confidence in the agent's
decisions over time, and to stay able to disagree with them. This describes the principles, and how
each one is implemented in the interface (`app/frontend`).

## 1. Design principles

### Show your working

Every decision includes the evidence chain: which fields were compared, what the values were, and
why the agent reached its conclusion. This is not optional; it is the primary interface.

*As built.* The invoice screen leads with the decision and the confidence, then the brief, then a
side-by-side table of invoice against PO and goods receipt with every mismatch marked. Evidence
links open the source invoice, the matched PO, competing candidate POs and the goods receipt in a
side panel. An audit record shows the raw and calibrated confidence and every model call.

### Distinguish certainty from uncertainty

Colour-coded confidence bands (green > 90%, amber 70–90%, red < 70%) let analysts scan a batch and
focus on uncertain cases first.

*As built.* The review queue opens on "Needs review", sorted least-confident first. Bands appear as
a coloured dot **with the percentage and a word** ("75% Medium"), never colour alone, so they
survive colour blindness and greyscale printing.

### Make overrides easy and valuable

Overriding should take fewer clicks than investigating from scratch, and should feel like teaching
the system rather than fighting it.

*As built.* Approve, Reject and Hold are one click, pre-selected to match the agent's decision where
it made one. Reclassifying is one dropdown. A reason code appears **only when the decision actually
overrides the agent** ([D-12](decision-log.md#d-12-confirming-an-escalation-is-a-review-not-an-override)), so
confirming an escalation stays a single click. The panel says plainly when a decision will be
recorded as an override, and why that matters.

### Never claim more than you know

The agent says "I matched this invoice to PO-2026-004817 because the supplier name and amount are
consistent (match score: 0.94)" rather than "This invoice belongs to PO-2026-004817." The hedge is
not weakness; it is calibration.

*As built.* The agent speaks in the first person and names its method and score: "Matched to
PO-2026-801319 by supplier, amount and line items (match score 1.00); the invoice did not quote a
valid PO reference." Every figure in a brief comes from a deterministic check — the model is only
allowed to write the narrative sentences, never the numbers.

### Degrade gracefully

When the agent cannot extract a field it says so and shows what it could extract. When it cannot
find a PO match it shows the best candidates. When it cannot classify an exception it escalates
with "I found these discrepancies but could not determine the root cause."

*As built.* Every model-backed step falls back to rules when the model is unavailable. An invoice
that cannot be read reliably gets a manual-entry brief naming the arithmetic that failed, rather
than a guess. The audit record shows which steps fell back, so nothing is silently degraded.

## 2. Escalation brief structure

| Section | Content |
|---|---|
| Summary | One line: "Invoice MFL26-7941 from Marlow & Finch Legal Services LLP: invoice subtotal £19,257.23 vs PO total £17,028.54: difference +£2,228.69 (+13.09%), tolerance £50.00" |
| What I found | Field-by-field comparison showing each discrepancy with both values |
| What I checked | The steps completed: PO match and score, GR availability, duplicate check, tax recalculation |
| What I could not resolve | Why this needs a human, with the confidence attached |
| Recommended action | A specific next step naming the person: "Confirm the price change with L. Nowak (PO approver) or request a credit note for the difference." |
| Evidence | Links to the source invoice, matched PO, goods receipt, candidate POs and any prior invoice |

The factual sections are always template-generated from the checks. Only the summary, the
unresolved line and the recommendation are written by the model, from those same facts, and they
fall back to templates when it is unavailable.

## 3. Oversight for the manager and the controller

- **Dashboard (US-04).** Exception volumes by type, what the agent did, how confident it was,
  suppliers with the most exceptions, and the override reasons analysts have given. Targets are
  shown next to the numbers, with an icon and text for pass or miss, so a missed target is legible
  without colour.
- **Reversed autonomous decisions.** Auto-decisions an analyst undid are counted separately: this is
  the early-warning signal for the false-approval rate.
- **Autonomy recommendations.** The dashboard reports, per exception category, how often analysts
  overrode the agent and whether the evidence supports moving that category in or out of autonomy
  ([D-16](decision-log.md#d-16-autonomy-is-recommended-by-evidence-never-widened-by-the-agent-itself)).
  This is what makes override capture worth an analyst's time: the reason codes they enter are
  visibly the thing that decides what the agent is allowed to do next.
- **Policy sandbox.** The manager can re-run the processed batch under different tolerances,
  confidence thresholds and autonomy boundaries, and see exactly which invoices change hands. It
  names the sum of money that would move from "an analyst sees this" to "paid automatically", so
  widening autonomy is a decision taken with a number attached. It replays recorded model responses,
  so exploring is free and cannot touch a live bill.
- **Audit trail (US-05).** Every decision, with reasoning, confidence, match method and score,
  discrepancies, model calls and the analyst's review, exportable as CSV — including auto-approved
  invoices on their own, which is the population an auditor asks about first.
- **"How the agent decides".** A plain-English panel showing the thresholds, the autonomy boundary
  and the tolerance rule in force, read live from the API, so the interface can never drift from the
  configuration.

## 4. What is not built

- **The loop informs; it does not yet adapt.** Override rates now drive explicit recommendations to
  widen or narrow autonomy, and a manager applies them. What is still absent is anything learned
  automatically — per-supplier tolerances inferred from "contractual adjustment" overrides, for
  instance. The agent's behaviour changes when a person changes it.
- **No per-analyst view or workload routing.**
- **Confidence is uncalibrated in the shipped configuration** (D-04), so bands currently understate
  certainty. Fitting the calibration table on a live run is a prerequisite for trusting the bands.
