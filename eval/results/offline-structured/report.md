# Evaluation report: offline-structured

- **Mode:** offline
- **Input:** structured (500 of 500 invoices)
- **Model:** none
- **Calibration:** none (identity)
- **Run at:** 2026-09-19 19:38 UTC, 0.1s wall clock

## Results against PRD thresholds (§5.2)

| Metric | Result | Target | Pass |
|---|---|---|---|
| extraction accuracy | n/a | > 95.0% | n/a |
| match accuracy | 100.00% | > 98.0% | ✅ |
| classification accuracy | 100.00% | > 90.0% | ✅ |
| calibration error | 14.49% | < 5.0% | ❌ |
| auto resolution precision | 100.00% | > 99.5% | ✅ |
| escalation recall | 100.00% | > 99.0% | ✅ |
| median latency s | 0.000s | < 30s | ✅ |
| cost per invoice gbp | £0.0000 | < £0.15 | ✅ |

Also: action accuracy 100.00%, auto-reject precision 100.00%, false approvals 0.

## Product metrics (§1.6)

- Auto-resolution rate: **32.5%** of exceptions (target 40–60%)
- Straight-through rate: 73.0% of all invoices decided without a human
- Actions: {'auto_approve': 340, 'auto_reject': 25, 'escalate': 135}

## By exception category

| Code | n | Precision | Recall |
|---|---|---|---|
| E01 | 40 | 100.00% | 100.00% |
| E02 | 25 | 100.00% | 100.00% |
| E03 | 30 | 100.00% | 100.00% |
| E04 | 25 | 100.00% | 100.00% |
| E05 | 30 | 100.00% | 100.00% |
| E06 | 15 | 100.00% | 100.00% |
| E07 | 20 | 100.00% | 100.00% |
| E08 | 15 | 100.00% | 100.00% |
| clean | 300 | 100.00% | 100.00% |

## Edge cases (§5.1)

| Tag | n | Classification | Action |
|---|---|---|---|
| ambiguous_candidates | 6 | 100.00% | 100.00% |
| ambiguous_name_typo | 3 | 100.00% | 100.00% |
| benign_name_variant | 25 | 100.00% | 100.00% |
| gr_notes_only | 5 | 100.00% | 100.00% |
| no_goods_receipt | 10 | 100.00% | 100.00% |
| no_po_exists | 10 | 100.00% | 100.00% |
| po_ref_format_variant | 10 | 100.00% | 100.00% |
| recurring_similar_invoice | 10 | 100.00% | 100.00% |

## Calibration (D-04)

Calibration error (PRD definition, mean gap per bucket): 14.49%; size-weighted ECE: 2.14%. After cross-fitted isotonic calibration: 0.40%.

| Confidence | n | Mean stated | Actual accuracy |
|---|---|---|---|
| 0.7-0.8 | 5 | 0.750 | 1.000 |
| 0.8-0.9 | 13 | 0.830 | 1.000 |
| 0.9-1.0 | 482 | 0.985 | 1.000 |

## Cost and latency

- LLM calls: 0 (0 fell back to rules), 0 input / 0 output tokens
- Cost: $0.00 (£0.00), £0.0000 per invoice
- Latency per invoice: median 0 ms, p90 0 ms

## Failures (0)

None.

## Caveats

- The synthetic data was generated with the same rules the agent applies, so rule-based steps are expected to score near 100%. Real invoices will be messier. These results are an upper bound for the deterministic steps and a regression baseline, not a production accuracy estimate.
- No LLM was used: extraction was not exercised (structured input), and GR notes, root-cause and brief steps used their rule-based fallbacks.
- Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.
