# Model card: InvoiceAgent

Version 0.1 · September 2026 · Status: prototype, not deployed

This card describes the whole system, not a trained model. InvoiceAgent is a pipeline of
deterministic rules with four Claude-backed steps; most of its behaviour comes from the rules and
thresholds recorded in the [decision log](decision-log.md).

## Intended use

**Intended.** Triage of accounts-payable exceptions in a batch workflow: read invoices, match them
to purchase orders and goods receipts, classify why they do not match, auto-resolve only the
lowest-risk cases, and escalate the rest to an AP analyst with a written brief and evidence.

**Intended users.** AP analysts (primary), AP managers (oversight), finance controllers (audit).
The agent assumes a human reviews everything it escalates.

**Not intended for.** Paying invoices (it recommends; it never pays), fraud detection beyond
duplicate identification, multi-currency reconciliation, contract or tax advice, or any use where
no human reviews escalations. It is not a system of record.

## How it works

Five steps: extract → match → validate → classify → report. The split between rules and the model
is deliberate ([D-03](decision-log.md#d-03-llm-used-selectively-not-end-to-end)):

| Step | Model? | Why |
|---|---|---|
| Extract | Yes | Invoice layouts vary too much for templates |
| Match (exact and fuzzy) | No | String comparison and similarity scoring are deterministic |
| Validate (amounts, quantities, tax, duplicates) | No | Arithmetic and comparison are deterministic and must be auditable |
| Validate (goods-receipt notes) | Yes | Free text: "Box 3 damaged, returned 5 units" |
| Classify (single discrepancy) | No | Direct mapping from finding to category |
| Classify (overlapping discrepancies) | Yes | Which finding is the root cause needs judgement |
| Report (data fields) | No | Template population; every figure traceable to a check |
| Report (narrative) | Yes | Explaining the finding to a person |

**The model cannot widen its own authority.** Autonomy rules are applied after the model's answer,
and it may only choose among findings the deterministic checks produced. Every model-backed step
has a rule-based fallback, so the agent still functions when the API is unavailable or a response
is refused.

Model: `claude-opus-5`, medium effort, structured JSON output, with server-side refusal fallbacks
([D-13](decision-log.md#d-13-claude-opus-5-with-server-side-refusal-fallbacks)). Gemini is supported
behind the same interface ([D-15](decision-log.md#d-15-a-second-provider-for-evaluation-only)); the
only live run so far used it, so those results describe that model rather than the shipping one.

## Autonomy boundary

| Outcome | When | Threshold |
|---|---|---|
| Auto-approve | Clean, or amount within tolerance (E01) | ≥ 95% confidence |
| Auto-reject | Duplicate (E04) | ≥ 85% confidence |
| Escalate | Everything else, and anything less certain | — |

Tolerance defaults to 1% or £50, whichever is smaller, configurable per supplier or cost centre
([D-02](decision-log.md#d-02-tolerance-thresholds-are-configurable-not-hardcoded)). Thresholds are
asymmetric by design: a false approval costs money, a false escalation costs two minutes
([D-06](decision-log.md#d-06-asymmetric-error-costs-reflected-in-the-escalation-threshold)).

## Training and evaluation data

No model was trained or fine-tuned. All evaluation uses a **synthetic dataset**: 500 invoices, 501
purchase orders and 476 goods receipts, entirely fictional, UK conventions (GBP, 20% VAT, Net
30/60). It was generated to the distribution in the PRD, with labelled exceptions and tagged
ambiguous cases ([data/generator/README.md](../data/generator/README.md)).

**The most important limitation of this card.** The data was generated from the same rules the agent
applies. Rule-based steps therefore score near 100% by construction. These results are a regression
baseline and a safety test, not evidence of production accuracy. No real invoice has ever been
through this system.

## Performance

Measured on the synthetic set; full results in [eval/results/SUMMARY.md](../eval/results/SUMMARY.md).

| Metric | Target | Result | |
|---|---|---|---|
| Match accuracy | > 98% | 100% | ✅ |
| Classification accuracy | > 90% | 100% | ✅ |
| Auto-resolution precision | > 99.5% | 100% | ✅ |
| Escalation recall | > 99% | 100% | ✅ |
| Calibration error | < 5% | 14.5% as-is; 0.4% fitted | ❌ not installed, see [D-04](decision-log.md#d-04-confidence-scores-are-calibrated-not-raw-model-probabilities) |
| Auto-resolution rate | 40–60% | 32.5% | ❌ ceiling under [D-01](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold) |
| Extraction accuracy | > 95% | 100% of fields on every invoice read, 27-invoice pilot | ⚠️ small sample, alternative model |
| Median latency | < 30 s | 23.8 s (42.9 s in an earlier sitting) | ⚠️ measured on 5 unthrottled invoices |
| Cost per invoice | < £0.15 | projected £0.011–£0.052 | projection only |

**Robustness.** With misreads injected into up to 100% of invoices at 95% stated confidence, **369
of 369 payment-affecting misreads were caught** by the arithmetic checks or the three-way match, and
no unsafe invoice was auto-approved.

## Limitations and risks

1. **Not validated on real invoices.** Every number above comes from synthetic data.
2. **Extraction is the weakest link and the least tested.** It has been exercised on 27 invoices
   with Gemini 3 Flash, not on the shipping model and not at volume.
3. **Confidence is under-calibrated in the shipped configuration.** Bands understate certainty; the
   calibration table should be fitted on live results before the bands are trusted.
4. **Auto-resolution cannot reach its target** under the current autonomy boundary — a product
   decision, not a model failure.
5. **Adversarial invoices are out of scope.** Nothing here resists an invoice crafted to exploit
   extraction or matching.
6. **Single currency, standard-rated VAT only.** Zero-rated and exempt items are not modelled.
7. **The feedback loop is half-built.** Overrides are captured but do not yet change behaviour.
8. **Only some production failure modes observed.** Throttling (429) and overloaded models (503)
   have now been seen against a real API, and both are retried; the 503 handling was added *because*
   a live run exposed it. Refusals, truncation and malformed structured output are still only
   unit-tested against a stub.

Full analysis: [failure taxonomy](failure-taxonomy.md).

## Human oversight

Analysts review every escalation and can override any decision, including reversing an
auto-approval or auto-rejection. Overrides require a structured reason code
([D-05](decision-log.md#d-05-override-reasons-are-structured-not-free-text)), which feeds the
dashboard's account of where the agent goes wrong. Every decision carries an audit record — inputs,
match method and score, discrepancies, raw and calibrated confidence, model calls, and the
analyst's review — exportable as CSV.

## Monitoring and rollback

Rollback to manual processing if any of the following holds
([evaluation framework](evaluation-framework.md#5-rollback-criteria)):

- Auto-resolution precision below 98%, measured weekly
- Analyst override rate above 25% for two consecutive weeks
- Any auto-approved invoice causing a loss above £10,000
- Extraction accuracy below 90%, indicating a shift in invoice formats

The first two are computable from the dashboard and review log today. The others need production
feedback this prototype does not collect.

## What would have to be true before deployment

1. A live evaluation over the full document set, with extraction accuracy, latency and cost measured.
2. A calibration table fitted on those results, and the confidence bands re-checked.
3. A pilot on real invoices, shadow-mode first: the agent proposes, humans decide, and the two are
   compared before any autonomy is switched on.
4. Persistence, authentication and access control — none of which exist here.
5. A resolution of the auto-resolution ceiling ([D-01](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold))
   and the extraction-confidence question ([D-11](decision-log.md#d-11-extraction-confidence-is-multiplied-into-classification-confidence)).
