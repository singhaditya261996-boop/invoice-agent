# Evaluation report: live-gemini3-documents-n8

- **Mode:** live
- **Input:** documents (11 of 500 invoices)
- **Model:** gemini-3-flash-preview (google)
- **Calibration:** none (identity)
- **Run at:** 2026-09-20 00:14 UTC, 269.7s wall clock

## Results against PRD thresholds (§5.2)

| Metric | Result | Target | Pass |
|---|---|---|---|
| extraction accuracy | 93.30% | > 95.0% | ❌ |
| match accuracy | 100.00% | > 98.0% | ✅ |
| classification accuracy | 90.91% | > 90.0% | ✅ |
| calibration error | 6.26% | < 5.0% | ❌ |
| auto resolution precision | 100.00% | > 99.5% | ✅ |
| escalation recall | 100.00% | > 99.0% | ✅ |
| median latency s | 42.944s | < 30s | ❌ |
| cost per invoice gbp | £0.0000 | < £0.15 | ✅ |

Also: action accuracy 90.91%, auto-reject precision 100.00%, false approvals 0.

## Product metrics (§1.6)

- Auto-resolution rate: **42.9%** of exceptions (target 40–60%)
- Straight-through rate: 54.5% of all invoices decided without a human
- Actions: {'auto_approve': 4, 'auto_reject': 2, 'escalate': 5}

## Extraction

- Field accuracy: 93.30% (on invoices extracted: 100.00%)
- Flagged for manual entry: 9.09%
- Invoices with any wrong field: 1
- Most-missed fields: {'<not extracted>': 1}

## By exception category

| Code | n | Precision | Recall |
|---|---|---|---|
| E01 | 1 | 100.00% | 100.00% |
| E02 | 2 | 100.00% | 100.00% |
| E03 | 2 | 100.00% | 100.00% |
| E04 | 3 | 100.00% | 66.67% |
| clean | 3 | 100.00% | 100.00% |

## Edge cases (§5.1)

| Tag | n | Classification | Action |
|---|---|---|---|
| gr_notes_only | 1 | 100.00% | 100.00% |
| no_goods_receipt | 1 | 100.00% | 100.00% |

## Calibration (D-04)

Calibration error (PRD definition, mean gap per bucket): 6.26%; size-weighted ECE: 4.78%. After cross-fitted isotonic calibration: 12.73%.

| Confidence | n | Mean stated | Actual accuracy |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.000 | 0.000 |
| 0.8-0.9 | 2 | 0.837 | 1.000 |
| 0.9-1.0 | 8 | 0.975 | 1.000 |

## Cost and latency

- LLM calls: 24 (2 fell back to rules), 8,496 input / 19,959 output tokens
- Cost: $0.00 (£0.00), £0.0000 per invoice
- Latency per invoice: median 42944 ms, p90 88788 ms

## Failures (1)

| Doc | Expected | Got | Conf. | Detail |
|---|---|---|---|---|
| DOC-0201 | E04/auto_reject (resubmitted_date_shift) | unclassified/escalate | 0.00 | LLM extraction unavailable |

## Caveats

- The synthetic data was generated with the same rules the agent applies, so rule-based steps are expected to score near 100%. Real invoices will be messier. These results are an upper bound for the deterministic steps and a regression baseline, not a production accuracy estimate.
- Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.
