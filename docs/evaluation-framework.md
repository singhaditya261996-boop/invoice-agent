# Evaluation framework

How the agent is measured, what has been measured so far, and what the numbers do and do not mean.
Latest results: [eval/results/SUMMARY.md](../eval/results/SUMMARY.md).

## 1. Test dataset

The synthetic dataset (500 invoices, 501 POs, 476 goods receipts) is the primary evaluation set.
Every invoice carries a ground-truth label: the correct exception code, the correct action, the PO
it really belongs to, and, for duplicates, the original it copies. Generation and its deviations
from the data spec: [data/generator/README.md](../data/generator/README.md).

The set includes deliberately ambiguous cases, tagged so they can be reported separately:

| Tag | n | What it tests |
|---|---|---|
| `benign_name_variant` | 25 | "Ltd" vs "Limited" must not become E08 |
| `po_ref_format_variant` | 10 | `PO2026004817` must not become E05 |
| `recurring_similar_invoice` | 10 | Monthly retainers must not become E04 |
| `ambiguous_candidates` | 6 | A near-identical competing PO |
| `gr_notes_only` | 5 | Shortfall recorded only in free-text notes |
| `ambiguous_name_typo` | 3 | Two-character supplier typos |
| `no_goods_receipt` | 10 | Three-way match cannot be completed |
| `no_po_exists` | 10 | Correct answer is "no match" |

## 2. Metrics

PRD targets, plus four metrics added during the build (marked *added*).

| Metric | What it measures | Target |
|---|---|---|
| Extraction accuracy | Fields correctly read, against ground truth | > 95% |
| Match accuracy | Correct PO found, or correctly reported as unmatchable | > 98% |
| Classification accuracy | Correct exception code | > 90% |
| Calibration error | Mean gap between stated confidence and actual accuracy per bucket | < 5% |
| Auto-resolution precision | Of auto-approved invoices, how many were genuinely safe | > 99.5% |
| Escalation recall | Of genuinely problematic invoices, how many avoided auto-approval | > 99% |
| Median latency | Time per invoice | < 30 s |
| Cost per invoice | Model spend | < £0.15 |
| *Auto-reject precision* | Of auto-rejected invoices, how many were really duplicates | reported |
| *Action accuracy* | Correct action, not just correct category | reported |
| *Misreads caught* | Payment-affecting misreads stopped before approval | 100% |
| *Cross-fitted calibration error* | Calibration error after fitting on held-out halves | < 5% |
| *Latency coverage* | Invoices whose model calls ran fresh, so latency is real | reported |

Two definitions worth stating, because they decide what counts as a failure:

- **Genuinely problematic** means the true label is anything other than clean or E01. An
  auto-rejected duplicate counts as caught: it was not approved.
- **Payment-affecting** means a misread field that could change who is paid or how much: amounts,
  quantities, unit prices, PO reference, supplier name. A misread invoice date or per-line VAT does
  not change the amount paid.

## 3. Protocol

```bash
python -m eval.run_eval --mode offline                       # rules only, free
python -m eval.run_eval --estimate --input documents         # projected live cost, free
python -m eval.run_eval --simulate-extraction-errors 0.3     # robustness, free
python -m eval.run_eval --mode live --input documents --max-cost-usd 40 --fit-calibration
```

Each run writes `eval/results/<run>/`: `report.md`, `metrics.json`, and `results.jsonl` with the
full audit record per invoice. Live runs also record model responses, so a run can be re-scored, or
replayed as demo-mode fixtures, without spending again.

Invoices process in dataset order within each supplier, with suppliers in parallel. Duplicate
detection only ever compares invoices from the same supplier, so results match a sequential run;
`tests/test_eval.py` asserts this. Live runs stop at a spending cap.

## 4. Results so far

| Run | Classification | Auto-approve precision | Escalation recall | Auto-resolution |
|---|---|---|---|---|
| Rules only, structured | 100% | 100% | 100% | 32.5% |
| Documents, perfect extraction (simulated) | 100% | 100% | 100% | 12.5% |
| 30% of invoices misread (simulated) | 78.0% | 100% | 100% | 6.2% |
| Every invoice misread (simulated) | 28.4% | 100% | 100% | 0.5% |
| **Live pilot, 27 invoices, Gemini 3 Flash** | 100% | 100% | 100% | 16.7% |

Classification accuracy falls in the misread runs by design: the agent is classifying a different
invoice from the one the label describes. The safety metrics are what matter there, and **369 of
369 payment-affecting misreads were caught**, with no unsafe approvals.

**This is a regression baseline and a safety test, not a production accuracy estimate.** The data
was generated from the same rules the agent applies, so the rule-based steps score near 100% by
construction. Real invoices will be messier.

## Calibration

The agent is currently *under-confident*: every confidence bucket on this data is 100% accurate, so
the PRD-defined calibration error is 14.5% (size-weighted ECE 2.1%) — it fails the < 5% target by
claiming less certainty than it has.

Fitting an isotonic map on held-out halves brings it to **0.4%**, so the mechanism works. No
calibration table is installed, because fitting on data where the agent makes no mistakes pushes
every score to about 99.7% and erases the uncertainty signal on genuinely ambiguous cases — the
GR-notes-only E03s, currently amber at 75%, would read as near-certain. It should be fitted on the
live run, where real extraction errors give the fit something to learn from (D-04).

## 4b. The gate in CI

Two evaluation runs execute on every push, and the build fails if either misses its thresholds:

```bash
python -m eval.run_eval --mode offline --check                       # all 500, rules only
python -m eval.run_eval --simulate-extraction-errors 0.5 --check     # half deliberately misread
```

The first checks every threshold that can be measured without a model. The second checks only the
safety properties — auto-resolution precision, escalation recall, and that nothing with a misread
that affects payment was auto-approved — because a run that misreads half its invoices is *expected*
to classify them wrong; what matters is that none of them is paid.

Calibration is deliberately not gated: no table is installed, so the run reports it failing, and
blocking the build on a known-open target would only teach people to ignore the signal.

## 5. Rollback criteria

In production, any of these triggers a rollback to manual processing:

- Auto-resolution precision below 98% (measured weekly)
- Analyst override rate above 25% for two consecutive weeks
- Any single auto-approved invoice causing a loss above £10,000
- Extraction accuracy below 90%, indicating a change in invoice format distribution

The first two are computable today from the dashboard metrics (`overrides`, `auto_resolution_rate`)
and the review log; the third and fourth need production feedback the MVP does not collect.

## 6. What the evaluation has already caught

The evaluation is not only a scorecard; it found defects that the tests did not:

- Two double-payment paths, now fixed and covered by regression tests ([D-09](decision-log.md#d-09-invoices-awaiting-manual-entry-stay-in-the-duplicate-check-history), [D-10](decision-log.md#d-10-the-same-po-billed-twice-for-the-same-amount-is-a-duplicate-signal-on-any-date))
- A crash when an invoice was extracted but scored too low to classify
- The auto-resolution ceiling ([D-01 addendum](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold)) and the extraction-confidence penalty ([D-11](decision-log.md#d-11-extraction-confidence-is-multiplied-into-classification-confidence))

## 7. Not yet measured

The live pilot covered 27 invoices on an alternative model (Gemini 3 Flash, free tier), built over
four sittings because the free tier allows 20 requests per model per day; each reused the earlier
sittings' recorded responses so quota went only on what was not yet recorded. Extraction was
exercised for real: field accuracy 100% across all 27, classification and action accuracy 100%, and
median latency 23.8 s against a 30 s target, from the sitting whose calls ran without throttling.
Earlier sittings lost invoices to quota limits and to transient `503`s; each time the agent
escalated the affected invoice for manual entry rather than guessing.

Still outstanding: everything at full scale on the shipping model — extraction accuracy over 500
documents, goods-receipt note interpretation, root-cause choice on overlapping discrepancies, brief
quality at volume, real cost, and a calibration table fitted on those errors.
