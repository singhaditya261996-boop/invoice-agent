# Decision log

Product-level trade-offs and their rationale. D-01 to D-06 are from the original PRD; D-07 onwards
were made while building, and each one names the evidence that forced it.

## D-01: Autonomy boundary set at a conservative threshold

**Decision.** The agent auto-resolves only E01 (amount within tolerance) and E04 (clear duplicates)
in the MVP. All other exception types are escalated with a recommendation.

**Alternatives.** (a) Auto-resolve anything above 90% confidence. (b) Never auto-resolve; always
escalate with a recommendation.

**Rationale.** Option (a) exposes the business to financial risk before the agent has earned trust
through observed accuracy. Option (b) reduces the product to a classification tool rather than an
agent. The middle path auto-resolves only the lowest-risk exceptions, letting analysts verify the
agent's judgement on harder cases before autonomy widens. The boundary should widen over time based
on measured override rates per exception type.

**Addendum (v1.1).** Two consequences surfaced in the build.

1. *The 40–60% auto-resolution target cannot be reached under this rule.* E01 and E04 are 65 of the
   200 exceptions in the PRD's own distribution, so the ceiling is **32.5%** even for a perfect
   agent. Three ways forward: accept a lower MVP target; allow the "conditional" cases below; or
   treat widening autonomy, as this decision already plans, as how the target is eventually met.
   **Open — needs a product call.** The policy sandbox in the UI now quantifies each option against
   a processed batch: it reports the auto-resolution rate, the invoices that change hands, and the
   value that would be paid without a human. The decision stays open, but it is no longer a matter
   of opinion.
2. *E03 and E07 are always escalated.* The exception table in the data spec calls them
   "conditionally" auto-resolvable (E03 when the goods receipt confirms a partial delivery, E07 when
   recalculation resolves it), which contradicts this decision. The build follows D-01. Allowing
   both would raise the ceiling to 57.5%.

## D-02: Tolerance thresholds are configurable, not hardcoded

**Decision.** Amount tolerance defaults to 1% or £50, whichever is smaller, configurable per
supplier or cost centre.

**Rationale.** Different suppliers and spend categories have different acceptable variance. £50 on a
£500,000 infrastructure invoice is negligible; the same £50 on a £200 stationery order is 25% and
should be flagged. Percentage-only or absolute-only thresholds fail in one direction or the other.
"Whichever is smaller" defaults to caution.

**As built.** `Settings.tolerance_for(supplier_id, cost_centre)`: a supplier override beats a cost
centre override beats the default.

## D-03: LLM used selectively, not end-to-end

**Decision.** Model calls are restricted to extraction, ambiguous classification, goods-receipt
notes interpretation, and escalation brief generation. All matching, validation and single-exception
classification use deterministic logic.

**Alternatives.** (a) End-to-end model pipeline processing the whole invoice in one prompt.
(b) Fully deterministic system with template-based extraction.

**Rationale.** Option (a) is expensive, non-deterministic for auditable steps, and harder to debug.
Option (b) fails on extraction because invoice layouts vary too much for templates. The hybrid uses
the model where it adds value and deterministic logic where reliability and auditability matter more.

**As built.** Every model-backed step has a rule-based fallback, so the agent still works when the
API is unavailable, a response is refused, or no cached response exists. An `offline` mode makes
this the default for tests and for a deterministic baseline.

## D-04: Confidence scores are calibrated, not raw model probabilities

**Decision.** The confidence shown to the analyst is a calibrated probability, not a raw model
output. Calibration is measured and reported in the evaluation framework.

**Rationale.** LLMs are poorly calibrated; a raw 90% may correspond to 70% actual accuracy. Showing
uncalibrated confidence erodes trust, because analysts notice when "90% confident" calls are wrong
30% of the time.

**As built.** Each classification records a raw score and a calibrated score. The calibration table
is fitted from evaluation results by isotonic regression and is currently the identity, because
fitting it on rules-generated data where the agent makes no mistakes would push every score to
about 99.7% and erase the uncertainty signal on genuinely ambiguous cases. It should be fitted on
the live run. See [evaluation framework](evaluation-framework.md#calibration).

## D-05: Override reasons are structured, not free text

**Decision.** When an analyst overrides the agent, they choose from a predefined list of reason
codes, with an optional free-text note.

**Rationale.** Free text is hard to aggregate and learn from. Structured codes enable automated
analysis of where the agent fails most often, which feeds the feedback loop.

**As built.** Eight reason codes. A reason is required only when the analyst actually overrides
(see D-12), and the note is required for "Other". Reviews are appended to `var/reviews.jsonl` and
summarised on the dashboard.

## D-06: Asymmetric error costs reflected in the escalation threshold

**Decision.** The auto-approve confidence threshold (95%) is higher than the auto-reject threshold
for duplicates (85%). Ambiguous cases default to escalation.

**Rationale.** A false approval costs money. A false rejection of a duplicate costs an analyst five
minutes to verify. A false escalation costs two minutes to confirm. The thresholds reflect that
asymmetry: very sure before approving, moderately sure before rejecting a duplicate, escalate
anything uncertain.

---

## D-07: Test data follows the rules, not the data spec, where they conflict

**Decision.** Where the synthetic data specification contradicts the decision rules, the generator
follows the rules and the deviation is documented.

- E01 invoices carry a variance strictly inside the D-02 tolerance, not the spec's 0.1–2%.
- PO and goods-receipt counts follow from the invoice mix (501 and 476, not 200 each).

**Rationale.** Ground-truth labels have to agree with the rules the agent is scored against,
otherwise the evaluation punishes correct behaviour. A 1.5% variance labelled E01 is E02 by D-02,
and the agent would be marked wrong for applying the tolerance it was given. On counts: E01 and E02
are defined as invoice total versus PO total, so each invoice bills one whole PO, and 500 invoices
need roughly 470 POs. 36 further POs carry no invoice, as realistic noise for fuzzy matching.

**Full detail.** [data/generator/README.md](../data/generator/README.md).

## D-08: Where a supplier name difference becomes E08

**Decision.** Legal-suffix and formatting differences ("Ltd" vs "Limited", case, punctuation, "&"
vs "and") are clean. Initialisms, subsidiaries, parent entities, trading names and typos of two or
more characters are E08. One-character typos are not generated.

**Rationale.** The data model calls typos a "minor variation" while the data spec lists them under
E08, and the two cannot both hold. The line is drawn at whether the difference could indicate a
*different legal entity*, which is what makes E08 a payment risk. One-character typos sit exactly on
the line, so the test set does not assert an answer for them.

## D-09: Invoices awaiting manual entry stay in the duplicate-check history

**Decision.** An invoice flagged for manual data entry is recorded as *unverified* rather than
dropped. A later invoice from a similar supplier that matches it on invoice number, PO reference, or
amount and date is escalated as a possible duplicate — never auto-approved, and never auto-rejected.

**Evidence.** The extraction-error simulation found three invoices being paid twice: the original
was misread and set aside for manual entry, so a clean resubmission found nothing to match against
and was auto-approved. Regression test:
`tests/test_pipeline.py::test_resubmission_of_invoice_awaiting_manual_entry_is_not_approved`.

**Rationale.** An invoice that has been received exists, whether or not the system could read it.
Its fields are unreliable, so any single strong link is enough to hold the later invoice for a
human, and unreliable data must never be enough to reject one automatically.

## D-10: The same PO billed twice for the same amount is a duplicate signal on any date

**Decision.** A second invoice for the same amount against the same PO is flagged regardless of
date, and escalated rather than auto-rejected.

**Evidence.** In the simulation, a misread invoice date moved a duplicate outside the ±1-day window,
and a renumbered duplicate was then approved.

**Rationale.** A PO billed in full once should not be billed in full again, and that fact does not
depend on a date the system may have misread. It is escalated, not rejected, because two equal
instalments against one PO can be legitimate — the same asymmetry as D-06.

## D-11: Extraction confidence is multiplied into classification confidence

**Decision (provisional).** The agent's confidence in a classification is multiplied by its
confidence in the extraction that produced it.

**Consequence.** With a model reporting 95% extraction confidence, no E01 reaches the 95%
auto-approve bar, so document input auto-resolves 12.5% of exceptions where structured input
resolves 32.5%.

**Open question.** The simulation shows the arithmetic consistency checks catch misreads on their
own, which suggests the multiplication double-counts extraction risk. Two ways forward: fit the
calibration table on the live run (D-04's intended mechanism), or stop multiplying once the
consistency checks pass. **Deferred until there is live extraction data to fit against.**

## D-12: Confirming an escalation is a review, not an override

**Decision.** An analyst decision is recorded as an override only when it changes the agent's
classification or reverses a decision the agent made autonomously. Approving an escalated invoice
after checking it is a review. A reason code is required only for overrides.

**Rationale.** The override rate is a measure of agent accuracy (PRD target: under 15%). Counting
routine confirmations as overrides would inflate it and make the metric useless. It would also put a
mandatory dropdown in front of the most common action an analyst takes, which conflicts with
"overriding should take fewer clicks than investigating from scratch" (trust design §7.1).

## D-13: Claude Opus 5, with server-side refusal fallbacks

**Decision.** The default model is `claude-opus-5` with `fallbacks: "default"`, so a refused request
is retried server-side on another model rather than failing.

**Rationale.** Anthropic's current guidance is to default to the most capable model and not to
downgrade for cost without measuring. The projected cost is $7–$33 for a 500-invoice document run
(£0.011–£0.052 per invoice against a £0.15 target), so cost does not force a cheaper model. The
model and effort level are single settings, and the evaluation reports cost per invoice, so this can
be revisited with measurements.

## D-14: Batches are in-memory; only reviews persist

**Decision.** Batch results live in the API process. Analyst reviews are appended to a JSONL log.

**Rationale.** MVP scope: the demo dataset reprocesses in about a second, so losing batches on
restart costs nothing. Override data is the one thing that cannot be regenerated, because it comes
from people, so it is the one thing written to disk. A real deployment needs a database for both.

## D-15: A second provider, for evaluation only

**Decision.** Gemini is supported behind the same interface as Claude, selected with
`--provider google`. Claude remains the default and the model the product is designed around.

**Rationale.** Anthropic API credit was not available, and an unexercised extraction step was the
biggest hole in the evaluation. A free provider made it possible to run real documents through the
whole pipeline and see the model-written briefs, which is worth more than another synthetic run.
The provider seam is small — one class implementing `json(task, system, content, schema)` plus a
schema translation — so this costs little and keeps the default honest.

**Constraint on the results.** Any figure produced this way describes that model. Every document
reporting pilot numbers names the model beside them, and the shipping-model run remains outstanding.
The free tier allows 20 requests per model per day, which is why the pilot is 27 invoices, built
over three sittings; each reuses the earlier sittings' recorded responses so quota goes only on
invoices not yet measured.

## D-16: Autonomy is recommended by evidence, never widened by the agent itself

**Decision.** The agent measures its own override rate per exception category and recommends where
the autonomy boundary should move. A person applies the change. Three guards:

1. **A minimum of 40 reviews per category.** Below that the sample cannot support a recommendation.
2. **The test uses the upper bound of the override rate, not the rate itself** (Wilson, 95%), so a
   short lucky run cannot look like evidence. Widening requires 95% confidence that the category's
   true override rate is already under the PRD's own 15% target.
3. **Some categories are never eligible, whatever the evidence.** E02, E05, E06 and E08 stay with a
   human permanently.

**Rationale.** D-01 always intended the boundary to widen on measured override rates, but nothing
measured them. The first two guards are about statistics; the third is the product judgement.

The simulated review history made the point concretely: analysts almost never override E02 (amount
over tolerance), so a naive rule recommended automating it. But a low override rate means the agent
*categorises* E02 correctly — it says nothing about whether a machine should authorise paying more
than the purchase order allows. Override rate measures accuracy; autonomy is a question of
authority. The eligible set is therefore drawn from the exception taxonomy's own "always escalate"
column rather than from any metric.

**Why the agent never applies its own recommendation.** An agent that expands its authority on the
strength of its own metrics is exactly the failure this product exists to avoid, and the audit story
to a controller would be indefensible. The recommendation names the change; the policy sandbox
quantifies it; a manager makes it.
