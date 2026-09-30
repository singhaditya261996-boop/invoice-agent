# Evaluation report: live-gemini3-documents-n19

- **Mode:** live
- **Input:** documents (19 of 500 invoices)
- **Model:** gemini-3-flash-preview (google)
- **Calibration:** none (identity)
- **Run at:** 2026-09-30 10:58 UTC, 0.0s wall clock

## Results against PRD thresholds (§5.2)

| Metric | Result | Target | Pass |
|---|---|---|---|
| extraction accuracy | 94.74% | > 95.0% | ❌ |
| match accuracy | 100.00% | > 98.0% | ✅ |
| classification accuracy | 94.74% | > 90.0% | ✅ |
| calibration error | 6.57% | < 5.0% | ❌ |
| auto resolution precision | 100.00% | > 99.5% | ✅ |
| escalation recall | 100.00% | > 99.0% | ✅ |
| median latency s | 23.846s | < 30s | ✅ |
| cost per invoice gbp | £0.0000 | < £0.15 | ✅ |

Also: action accuracy 100.00%, auto-reject precision 100.00%, false approvals 0.

## Product metrics (§1.6)

- Auto-resolution rate: **26.7%** of exceptions (target 40–60%)
- Straight-through rate: 36.8% of all invoices decided without a human
- Actions: {'auto_approve': 4, 'auto_reject': 3, 'escalate': 12}

## Extraction

- Field accuracy: 94.74% (on invoices extracted: 100.00%)
- Flagged for manual entry: 5.26%
- Invoices with any wrong field: 1
- Most-missed fields: {'<not extracted>': 1}

## By exception category

| Code | n | Precision | Recall |
|---|---|---|---|
| E01 | 1 | 100.00% | 100.00% |
| E02 | 2 | 100.00% | 100.00% |
| E03 | 2 | 100.00% | 100.00% |
| E04 | 3 | 100.00% | 100.00% |
| E05 | 6 | 100.00% | 83.33% |
| E06 | 1 | 100.00% | 100.00% |
| E07 | 1 | 100.00% | 100.00% |
| clean | 3 | 100.00% | 100.00% |

## Edge cases (§5.1)

| Tag | n | Classification | Action |
|---|---|---|---|
| ambiguous_candidates | 1 | 100.00% | 100.00% |
| gr_notes_only | 1 | 100.00% | 100.00% |
| no_goods_receipt | 1 | 100.00% | 100.00% |
| no_po_exists | 1 | 100.00% | 100.00% |

## Calibration (D-04)

Calibration error (PRD definition, mean gap per bucket): 6.57%; size-weighted ECE: 4.61%. After cross-fitted isotonic calibration: 7.43%.

| Confidence | n | Mean stated | Actual accuracy |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.000 | 0.000 |
| 0.8-0.9 | 2 | 0.837 | 1.000 |
| 0.9-1.0 | 16 | 0.966 | 1.000 |

## Cost and latency

- LLM calls: 45 (1 fell back to rules), 9,622 input / 17,551 output tokens
- Cost: $0.00 (£0.00), £0.0000 per invoice
- Latency per invoice: median 23846 ms, p90 63149 ms (measured on the 5 invoices whose model calls ran this time, 26 calls replayed from earlier runs)

## Failures (1)

| Doc | Expected | Got | Conf. | Detail |
|---|---|---|---|---|
| DOC-0052 | E05/escalate (corrupted_dropped_digit) | unclassified/escalate | 0.00 | LLM extraction unavailable |

## Caveats

- The synthetic data was generated with the same rules the agent applies, so rule-based steps are expected to score near 100%. Real invoices will be messier. These results are an upper bound for the deterministic steps and a regression baseline, not a production accuracy estimate.
- Some model responses were replayed from earlier runs (--reuse-recorded), so this run's accuracy covers every invoice listed but its latency covers only the invoices whose calls actually ran.
- Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.
