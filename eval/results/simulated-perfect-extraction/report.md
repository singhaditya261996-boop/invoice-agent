# Evaluation report: simulated-perfect-extraction

- **Mode:** offline (simulated extraction)
- **Input:** documents (500 of 500 invoices)
- **Model:** none
- **Calibration:** none (identity)
- **Run at:** 2026-09-19 19:38 UTC, 0.1s wall clock

## Results against PRD thresholds (§5.2)

| Metric | Result | Target | Pass |
|---|---|---|---|
| extraction accuracy | 100.00% | > 95.0% | ✅ |
| match accuracy | 100.00% | > 98.0% | ✅ |
| classification accuracy | 100.00% | > 90.0% | ✅ |
| calibration error | 14.21% | < 5.0% | ❌ |
| auto resolution precision | 100.00% | > 99.5% | ✅ |
| escalation recall | 100.00% | > 99.0% | ✅ |
| median latency s | 0.000s | < 30s | ✅ |
| cost per invoice gbp | £0.0000 | < £0.15 | ✅ |

Also: action accuracy 90.00%, auto-reject precision 100.00%, false approvals 0.

## Product metrics (§1.6)

- Auto-resolution rate: **12.5%** of exceptions (target 40–60%)
- Straight-through rate: 63.0% of all invoices decided without a human
- Actions: {'auto_approve': 290, 'auto_reject': 25, 'escalate': 185}

## Extraction

- Field accuracy: 100.00% (on invoices extracted: 100.00%)
- Flagged for manual entry: 0.00%
- Invoices with any wrong field: 0
- Most-missed fields: none

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
| po_ref_format_variant | 10 | 100.00% | 0.00% |
| recurring_similar_invoice | 10 | 100.00% | 100.00% |

## Calibration (D-04)

Calibration error (PRD definition, mean gap per bucket): 14.21%; size-weighted ECE: 7.03%. After cross-fitted isotonic calibration: 0.40%.

| Confidence | n | Mean stated | Actual accuracy |
|---|---|---|---|
| 0.7-0.8 | 15 | 0.760 | 1.000 |
| 0.8-0.9 | 28 | 0.875 | 1.000 |
| 0.9-1.0 | 457 | 0.939 | 1.000 |

## Cost and latency

- LLM calls: 1001 (501 fell back to rules), 0 input / 0 output tokens
- Cost: $0.00 (£0.00), £0.0000 per invoice
- Latency per invoice: median 0 ms, p90 0 ms

## Failures (50)

| Doc | Expected | Got | Conf. | Detail |
|---|---|---|---|---|
| DOC-0009 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £941.28 vs PO total £935.98: difference +£5.30 (+0.57%), tolerance £9.36 |
| DOC-0011 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £729.91 vs PO total £736.03: difference -£6.12 (-0.83%), tolerance £7.36 |
| DOC-0034 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0038 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,018.28 vs PO total £2,025.55: difference -£7.27 (-0.36%), tolerance £20.26 |
| DOC-0039 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0043 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0054 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,713.81 vs PO total £1,702.29: difference +£11.52 (+0.68%), tolerance £17.02 |
| DOC-0061 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0085 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £264.82 vs PO total £262.62: difference +£2.20 (+0.84%), tolerance £2.63 |
| DOC-0090 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,027.39 vs PO total £1,021.15: difference +£6.24 (+0.61%), tolerance £10.21 |
| DOC-0105 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,394.60 vs PO total £2,381.28: difference +£13.32 (+0.56%), tolerance £23.81 |
| DOC-0110 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £22,091.42 vs PO total £22,053.65: difference +£37.77 (+0.17%), tolerance £50.00 |
| DOC-0113 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £4,539.03 vs PO total £4,563.97: difference -£24.94 (-0.55%), tolerance £45.64 |
| DOC-0118 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £27,639.45 vs PO total £27,603.55: difference +£35.90 (+0.13%), tolerance £50.00 |
| DOC-0133 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £968.52 vs PO total £970.62: difference -£2.10 (-0.22%), tolerance £9.71 |
| DOC-0137 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,596.60 vs PO total £2,619.46: difference -£22.86 (-0.87%), tolerance £26.19 |
| DOC-0139 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,442.70 vs PO total £1,433.25: difference +£9.45 (+0.66%), tolerance £14.33 |
| DOC-0168 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £453.26 vs PO total £449.46: difference +£3.80 (+0.85%), tolerance £4.49 |
| DOC-0176 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0178 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,125.80 vs PO total £1,121.38: difference +£4.42 (+0.39%), tolerance £11.21 |
| DOC-0199 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £13,718.90 vs PO total £13,697.20: difference +£21.70 (+0.16%), tolerance £50.00 |
| DOC-0203 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £23,923.96 vs PO total £23,968.84: difference -£44.88 (-0.19%), tolerance £50.00 |
| DOC-0209 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £6,935.04 vs PO total £6,890.75: difference +£44.29 (+0.64%), tolerance £50.00 |
| DOC-0227 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £28,752.12 vs PO total £28,717.92: difference +£34.20 (+0.12%), tolerance £50.00 |
| DOC-0238 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,391.10 vs PO total £1,386.00: difference +£5.10 (+0.37%), tolerance £13.86 |
| DOC-0251 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £18,463.44 vs PO total £18,504.36: difference -£40.92 (-0.22%), tolerance £50.00 |
| DOC-0252 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £3,275.40 vs PO total £3,295.64: difference -£20.24 (-0.61%), tolerance £32.96 |
| DOC-0262 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0263 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0275 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0298 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0322 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £5,061.31 vs PO total £5,044.44: difference +£16.87 (+0.33%), tolerance £50.00 |
| DOC-0333 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,736.18 vs PO total £1,731.56: difference +£4.62 (+0.27%), tolerance £17.32 |
| DOC-0335 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £8,822.72 vs PO total £8,855.22: difference -£32.50 (-0.37%), tolerance £50.00 |
| DOC-0347 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £980.39 vs PO total £976.74: difference +£3.65 (+0.37%), tolerance £9.77 |
| DOC-0348 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £8,135.42 vs PO total £8,111.72: difference +£23.70 (+0.29%), tolerance £50.00 |
| DOC-0349 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0352 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £4,339.36 vs PO total £4,332.00: difference +£7.36 (+0.17%), tolerance £43.32 |
| DOC-0355 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,635.79 vs PO total £2,631.01: difference +£4.78 (+0.18%), tolerance £26.31 |
| DOC-0388 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £977.65 vs PO total £974.45: difference +£3.20 (+0.33%), tolerance £9.74 |

## Caveats

- The synthetic data was generated with the same rules the agent applies, so rule-based steps are expected to score near 100%. Real invoices will be messier. These results are an upper bound for the deterministic steps and a regression baseline, not a production accuracy estimate.
- Extraction was simulated, not performed by a model. The simulation tests the safeguards around extraction, not extraction quality itself.
- Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.
