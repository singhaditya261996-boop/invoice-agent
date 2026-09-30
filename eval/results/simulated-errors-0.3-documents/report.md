# Evaluation report: simulated-errors-0.3-documents

- **Mode:** offline (simulated extraction)
- **Input:** documents (500 of 500 invoices)
- **Model:** none
- **Calibration:** none (identity)
- **Run at:** 2026-09-19 19:38 UTC, 0.1s wall clock

## Results against PRD thresholds (§5.2)

| Metric | Result | Target | Pass |
|---|---|---|---|
| extraction accuracy | 98.43% | > 95.0% | ✅ |
| match accuracy | 98.85% | > 98.0% | ✅ |
| classification accuracy | 78.00% | > 90.0% | ❌ |
| calibration error | 35.24% | < 5.0% | ❌ |
| auto resolution precision | 100.00% | > 99.5% | ✅ |
| escalation recall | 100.00% | > 99.0% | ✅ |
| median latency s | 0.000s | < 30s | ✅ |
| cost per invoice gbp | £0.0000 | < £0.15 | ✅ |

Also: action accuracy 73.60%, auto-reject precision 100.00%, false approvals 0.

## Product metrics (§1.6)

- Auto-resolution rate: **6.2%** of exceptions (target 40–60%)
- Straight-through rate: 46.6% of all invoices decided without a human
- Actions: {'auto_approve': 220, 'auto_reject': 13, 'escalate': 267}

## Extraction

- Field accuracy: 98.43% (on invoices extracted: 98.43%)
- Flagged for manual entry: 12.80%
- Invoices with any wrong field: 152
- Most-missed fields: {'po_reference': 31, 'supplier_name': 22, 'invoice_date': 22, 'unit_price': 20, 'quantity': 16, 'tax': 13, 'total': 11, 'total_amount': 7, 'subtotal': 6, 'tax_amount': 4}

## Robustness to extraction errors (simulated)

152 invoices had one field misread (117 in a field that affects payment). The simulated model reported 95% confidence on every extraction, as an overconfident model would.

- Material misreads caught (manual entry or escalation): **117 of 117**
- Auto-approved despite a material misread: **0**

| Misread | Outcomes |
|---|---|
| date_misread | {'auto_approve': 16, 'escalate': 6} |
| decimal_shift | {'auto_approve': 5, 'manual_entry': 14, 'escalate': 1, 'auto_reject': 1} |
| digit_lookalike | {'manual_entry': 15, 'auto_approve': 2, 'escalate': 1} |
| digit_transposed | {'manual_entry': 19, 'auto_approve': 1, 'auto_reject': 1, 'escalate': 1} |
| po_ref_digit | {'escalate': 31} |
| quantity_misread | {'manual_entry': 16} |
| supplier_typo | {'escalate': 22} |

## By exception category

| Code | n | Precision | Recall |
|---|---|---|---|
| E01 | 40 | 100.00% | 77.50% |
| E02 | 25 | 100.00% | 72.00% |
| E03 | 30 | 100.00% | 70.00% |
| E04 | 25 | 100.00% | 88.00% |
| E05 | 30 | 47.27% | 86.67% |
| E06 | 15 | 100.00% | 100.00% |
| E07 | 20 | 100.00% | 90.00% |
| E08 | 15 | 41.38% | 80.00% |
| clean | 300 | 100.00% | 75.67% |

## Edge cases (§5.1)

| Tag | n | Classification | Action |
|---|---|---|---|
| ambiguous_candidates | 6 | 100.00% | 100.00% |
| ambiguous_name_typo | 3 | 66.67% | 100.00% |
| benign_name_variant | 25 | 88.00% | 88.00% |
| gr_notes_only | 5 | 100.00% | 100.00% |
| no_goods_receipt | 10 | 70.00% | 100.00% |
| no_po_exists | 10 | 80.00% | 100.00% |
| po_ref_format_variant | 10 | 70.00% | 0.00% |
| recurring_similar_invoice | 10 | 40.00% | 40.00% |

## Calibration (D-04)

Calibration error (PRD definition, mean gap per bucket): 35.24%; size-weighted ECE: 18.81%. After cross-fitted isotonic calibration: 14.88%.

| Confidence | n | Mean stated | Actual accuracy |
|---|---|---|---|
| 0.4-0.5 | 17 | 0.466 | 0.000 |
| 0.6-0.7 | 52 | 0.667 | 0.000 |
| 0.7-0.8 | 27 | 0.756 | 0.815 |
| 0.8-0.9 | 56 | 0.866 | 0.357 |
| 0.9-1.0 | 348 | 0.939 | 1.000 |

## Cost and latency

- LLM calls: 986 (486 fell back to rules), 0 input / 0 output tokens
- Cost: $0.00 (£0.00), £0.0000 per invoice
- Latency per invoice: median 0 ms, p90 0 ms

## Failures (157)

| Doc | Expected | Got | Conf. | Detail |
|---|---|---|---|---|
| DOC-0002 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-113526' does not exist; closest PO by supplier, amount and lines is PO-2026-713526 (score 1.00) |
| DOC-0004 | E02/escalate (price_error) | E08/escalate | 0.69 | Invoice supplier 'Marlow & Finh Legal Services LLP' vs PO supplier 'Marlow & Finch Legal Services LLP' (similarity 0.98) |
| DOC-0005 | clean/auto_approve (None) | unclassified/escalate | 0.47 | Line 2: 19 x £37.63 != £71.50 |
| DOC-0008 | clean/auto_approve (recurring_retainer) | E05/escalate | 0.88 | PO reference 'PO-2026-131389' does not exist; closest PO by supplier, amount and lines is PO-2026-131889 (score 1.00) |
| DOC-0009 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £941.28 vs PO total £935.98: difference +£5.30 (+0.57%), tolerance £9.36 |
| DOC-0010 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 7 x £2428.11 != £2428.11 |
| DOC-0011 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £729.91 vs PO total £736.03: difference -£6.12 (-0.83%), tolerance £7.36 |
| DOC-0021 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 328 x £79.41 != £6366.48 |
| DOC-0029 | clean/auto_approve (recurring_retainer) | unclassified/escalate | 0.47 | Line 1: 1 x £5959.47 != £595.95 |
| DOC-0031 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-874481' does not exist; closest PO by supplier, amount and lines is PO-2026-824481 (score 1.00) |
| DOC-0034 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0038 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,018.28 vs PO total £2,025.55: difference -£7.27 (-0.36%), tolerance £20.26 |
| DOC-0039 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0043 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0046 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2826-147566' does not exist; closest PO by supplier, amount and lines is PO-2026-147566 (score 1.00) |
| DOC-0050 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Ashdown Cateing Ltd' vs PO supplier 'Ashdown Catering Ltd' (similarity 0.97) |
| DOC-0054 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,713.81 vs PO total £1,702.29: difference +£11.52 (+0.68%), tolerance £17.02 |
| DOC-0059 | clean/auto_approve (None) | unclassified/escalate | 0.47 | Line 2: 200 x £8.69 != £173.80 |
| DOC-0061 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0064 | clean/auto_approve (None) | unclassified/escalate | 0.47 | Line 4: 48 x £374.95 != £19797.60 |
| DOC-0065 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 2: 74 x £115.48 != £2771.52 |
| DOC-0066 | E03/escalate (partial_delivery) | E05/escalate | 0.75 | PO reference 'PO-2026-100731' does not exist; closest PO by supplier, amount and lines is PO-2026-700731 (score 1.00); B |
| DOC-0082 | E05/escalate (maverick) | unclassified/escalate | 0.67 | Line 3: 12 x £53.57 != £426.84 |
| DOC-0085 | E01/auto_approve (price_adjustment) | unclassified/escalate | 0.67 | Line 1: 2 x £13.24 != £264.82 |
| DOC-0087 | E03/escalate (partial_delivery) | unclassified/escalate | 0.67 | Line 4: 25 x £158.55 != £4122.30 |
| DOC-0089 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Subtotal + VAT does not equal the total |
| DOC-0090 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £1,027.39 vs PO total £1,021.15: difference +£6.24 (+0.61%), tolerance £10.21 |
| DOC-0092 | clean/auto_approve (None) | unclassified/escalate | 0.47 | Line totals do not sum to the subtotal |
| DOC-0094 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-672399' does not exist; closest PO by supplier, amount and lines is PO-2026-672394 (score 1.00) |
| DOC-0096 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Northvale Facilities Managment plc' vs PO supplier 'Northvale Facilities Management plc' (similarity 0 |
| DOC-0105 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,394.60 vs PO total £2,381.28: difference +£13.32 (+0.56%), tolerance £23.81 |
| DOC-0106 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-523665' does not exist; closest PO by supplier, amount and lines is PO-2026-623665 (score 1.00) |
| DOC-0109 | E02/escalate (price_error) | unclassified/escalate | 0.67 | Line 2: 8 x £188.40 != £565.20 |
| DOC-0110 | E01/auto_approve (price_adjustment) | unclassified/escalate | 0.67 | Line 3: 3 x £54927.40 != £16478.22 |
| DOC-0113 | E01/auto_approve (price_adjustment) | unclassified/escalate | 0.67 | Subtotal + VAT does not equal the total |
| DOC-0116 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2025-519105' does not exist; closest PO by supplier, amount and lines is PO-2026-519105 (score 1.00) |
| DOC-0118 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £27,639.45 vs PO total £27,603.55: difference +£35.90 (+0.13%), tolerance £50.00 |
| DOC-0120 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2826-210612' does not exist; closest PO by supplier, amount and lines is PO-2026-210612 (score 1.00) |
| DOC-0124 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Subtotal + VAT does not equal the total |
| DOC-0125 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Meridian Office SuppliesLtd' vs PO supplier 'Meridian Office Supplies Ltd' (similarity 0.94) |

## Caveats

- The synthetic data was generated with the same rules the agent applies, so rule-based steps are expected to score near 100%. Real invoices will be messier. These results are an upper bound for the deterministic steps and a regression baseline, not a production accuracy estimate.
- Extraction was simulated, not performed by a model. The simulation tests the safeguards around extraction, not extraction quality itself.
- Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.
