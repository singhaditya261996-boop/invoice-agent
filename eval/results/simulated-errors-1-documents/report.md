# Evaluation report: simulated-errors-1-documents

- **Mode:** offline (simulated extraction)
- **Input:** documents (500 of 500 invoices)
- **Model:** none
- **Calibration:** none (identity)
- **Run at:** 2026-09-19 19:38 UTC, 0.1s wall clock

## Results against PRD thresholds (§5.2)

| Metric | Result | Target | Pass |
|---|---|---|---|
| extraction accuracy | 94.83% | > 95.0% | ❌ |
| match accuracy | 96.28% | > 98.0% | ❌ |
| classification accuracy | 28.40% | > 90.0% | ❌ |
| calibration error | 46.86% | < 5.0% | ❌ |
| auto resolution precision | 100.00% | > 99.5% | ✅ |
| escalation recall | 100.00% | > 99.0% | ✅ |
| median latency s | 0.000s | < 30s | ✅ |
| cost per invoice gbp | £0.0000 | < £0.15 | ✅ |

Also: action accuracy 40.80%, auto-reject precision 100.00%, false approvals 0.

## Product metrics (§1.6)

- Auto-resolution rate: **0.5%** of exceptions (target 40–60%)
- Straight-through rate: 13.8% of all invoices decided without a human
- Actions: {'auto_approve': 68, 'auto_reject': 1, 'escalate': 431}

## Extraction

- Field accuracy: 94.83% (on invoices extracted: 94.83%)
- Flagged for manual entry: 46.20%
- Invoices with any wrong field: 500
- Most-missed fields: {'invoice_date': 76, 'quantity': 72, 'supplier_name': 71, 'po_reference': 67, 'tax': 55, 'unit_price': 50, 'total': 46, 'subtotal': 23, 'total_amount': 22, 'tax_amount': 18}

## Robustness to extraction errors (simulated)

500 invoices had one field misread (369 in a field that affects payment). The simulated model reported 95% confidence on every extraction, as an overconfident model would.

- Material misreads caught (manual entry or escalation): **369 of 369**
- Auto-approved despite a material misread: **0**

| Misread | Outcomes |
|---|---|
| date_misread | {'auto_approve': 43, 'escalate': 32, 'auto_reject': 1} |
| decimal_shift | {'manual_entry': 46, 'escalate': 8, 'auto_approve': 8} |
| digit_lookalike | {'manual_entry': 48, 'auto_approve': 10, 'escalate': 8} |
| digit_transposed | {'auto_approve': 7, 'manual_entry': 65, 'escalate': 14} |
| po_ref_digit | {'escalate': 67} |
| quantity_misread | {'manual_entry': 72} |
| supplier_typo | {'escalate': 71} |

## By exception category

| Code | n | Precision | Recall |
|---|---|---|---|
| E01 | 40 | 100.00% | 22.50% |
| E02 | 25 | 100.00% | 28.00% |
| E03 | 30 | 100.00% | 40.00% |
| E04 | 25 | 85.71% | 48.00% |
| E05 | 30 | 19.18% | 46.67% |
| E06 | 15 | 100.00% | 60.00% |
| E07 | 20 | 100.00% | 20.00% |
| E08 | 15 | 7.04% | 33.33% |
| clean | 300 | 100.00% | 23.33% |

## Edge cases (§5.1)

| Tag | n | Classification | Action |
|---|---|---|---|
| ambiguous_candidates | 6 | 50.00% | 100.00% |
| ambiguous_name_typo | 3 | 66.67% | 100.00% |
| benign_name_variant | 25 | 24.00% | 24.00% |
| gr_notes_only | 5 | 40.00% | 100.00% |
| no_goods_receipt | 10 | 30.00% | 100.00% |
| no_po_exists | 10 | 20.00% | 100.00% |
| po_ref_format_variant | 10 | 20.00% | 0.00% |
| recurring_similar_invoice | 10 | 30.00% | 30.00% |

## Calibration (D-04)

Calibration error (PRD definition, mean gap per bucket): 46.86%; size-weighted ECE: 48.52%. After cross-fitted isotonic calibration: 16.36%.

| Confidence | n | Mean stated | Actual accuracy |
|---|---|---|---|
| 0.4-0.5 | 69 | 0.466 | 0.000 |
| 0.5-0.6 | 1 | 0.583 | 0.000 |
| 0.6-0.7 | 185 | 0.666 | 0.032 |
| 0.7-0.8 | 32 | 0.757 | 0.438 |
| 0.8-0.9 | 101 | 0.846 | 0.099 |
| 0.9-1.0 | 112 | 0.937 | 1.000 |

## Cost and latency

- LLM calls: 898 (398 fell back to rules), 0 input / 0 output tokens
- Cost: $0.00 (£0.00), £0.0000 per invoice
- Latency per invoice: median 0 ms, p90 0 ms

## Failures (380)

| Doc | Expected | Got | Conf. | Detail |
|---|---|---|---|---|
| DOC-0001 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-7026-212250' does not exist; closest PO by supplier, amount and lines is PO-2026-212250 (score 1.00) |
| DOC-0002 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-113526' does not exist; closest PO by supplier, amount and lines is PO-2026-713526 (score 1.00) |
| DOC-0003 | E03/escalate (partial_delivery) | E05/escalate | 0.75 | PO reference 'PO-2826-943012' does not exist; closest PO by supplier, amount and lines is PO-2026-943012 (score 1.00); E |
| DOC-0004 | E02/escalate (price_error) | E08/escalate | 0.69 | Invoice supplier 'Marlow & Finh Legal Services LLP' vs PO supplier 'Marlow & Finch Legal Services LLP' (similarity 0.98) |
| DOC-0005 | clean/auto_approve (None) | unclassified/escalate | 0.47 | Line 2: 19 x £37.63 != £71.50 |
| DOC-0007 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-738735' does not exist; closest PO by supplier, amount and lines is PO-2026-738135 (score 1.00) |
| DOC-0008 | clean/auto_approve (recurring_retainer) | E05/escalate | 0.88 | PO reference 'PO-2026-131389' does not exist; closest PO by supplier, amount and lines is PO-2026-131889 (score 1.00) |
| DOC-0009 | E01/auto_approve (price_adjustment) | unclassified/escalate | 0.47 | Line 1: 106 x £8.88 != £941.82 |
| DOC-0010 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 7 x £2428.11 != £2428.11 |
| DOC-0011 | E01/auto_approve (price_adjustment) | unclassified/escalate | 0.67 | Line 1: 34 x £17.99 != £441.66 |
| DOC-0012 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 76 x £23.65 != £614.90 |
| DOC-0013 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Larkspur Creatie Agency Ltd' vs PO supplier 'Larkspur Creative Agency Ltd' (similarity 0.98) |
| DOC-0015 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 7 x £2707.29 != £5414.58 |
| DOC-0016 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-211211' does not exist; closest PO by supplier, amount and lines is PO-2026-271211 (score 1.00) |
| DOC-0019 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-324369' does not exist; closest PO by supplier, amount and lines is PO-2026-324869 (score 1.00) |
| DOC-0021 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 328 x £79.41 != £6366.48 |
| DOC-0023 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 2: 1 x £13656.52 != £13656.62 |
| DOC-0024 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2826-326845' does not exist; closest PO by supplier, amount and lines is PO-2026-326845 (score 1.00) |
| DOC-0025 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Subtotal + VAT does not equal the total |
| DOC-0026 | clean/auto_approve (recurring_retainer) | unclassified/escalate | 0.47 | Line totals do not sum to the subtotal |
| DOC-0027 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 178 x £41.63 != £4912.34 |
| DOC-0028 | E06/escalate (late_invoice) | E05/escalate | 0.88 | PO reference 'PO-2026-768008' does not exist |
| DOC-0029 | clean/auto_approve (recurring_retainer) | E05/escalate | 0.88 | PO reference 'PO-2026-870593' does not exist |
| DOC-0030 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-085007' does not exist; closest PO by supplier, amount and lines is PO-2026-085002 (score 1.00) |
| DOC-0031 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 18 x £24.94 != £324.22 |
| DOC-0033 | clean/auto_approve (None) | E05/escalate | 0.88 | PO reference 'PO-2026-560414' does not exist; closest PO by supplier, amount and lines is PO-2026-550414 (score 1.00) |
| DOC-0034 | clean/auto_approve (po_ref_format_variant) | E05/escalate | 0.88 | PO reference 'PO2826348177' does not exist; closest PO by supplier, amount and lines is PO-2026-348177 (score 1.00) |
| DOC-0035 | clean/auto_approve (None) | unclassified/escalate | 0.47 | Line 2: 38 x £62.79 != £2386.20 |
| DOC-0038 | E01/auto_approve (price_adjustment) | E01/escalate | 0.92 | Invoice subtotal £2,018.28 vs PO total £2,025.55: difference -£7.27 (-0.36%), tolerance £20.26 |
| DOC-0039 | clean/auto_approve (po_ref_format_variant) | E05/escalate | 0.88 | PO reference 'PO2026543471' does not exist; closest PO by supplier, amount and lines is PO-2026-543421 (score 1.00) |
| DOC-0040 | E07/escalate (line_omitted) | E05/escalate | 0.75 | PO reference 'PO-2026-153485' does not exist; closest PO by supplier, amount and lines is PO-2026-753485 (score 1.00); S |
| DOC-0041 | E03/escalate (gr_notes_only) | unclassified/escalate | 0.47 | Line 3: 40 x £9.54 != £831.60 |
| DOC-0043 | clean/auto_approve (po_ref_format_variant) | clean/escalate | 0.94 | no discrepancies found |
| DOC-0045 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Meridian Office SuppliesLtd' vs PO supplier 'Meridian Office Supplies Ltd' (similarity 0.94) |
| DOC-0046 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Fenmoor Freigt Ltd' vs PO supplier 'Fenmoor Freight Ltd' (similarity 0.97) |
| DOC-0047 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 7 x £5099.46 != £5099.46 |
| DOC-0048 | E03/escalate (partial_delivery) | E08/escalate | 0.69 | Invoice supplier 'Brackenfield Packaging Ld' vs PO supplier 'Brackenfield Packaging Ltd' (similarity 0.94); Stretch wrap |
| DOC-0049 | E07/escalate (arithmetic_slip) | E08/escalate | 0.69 | Invoice supplier 'Northvale Facilities Managment plc' vs PO supplier 'Northvale Facilities Management plc' (similarity 0 |
| DOC-0050 | clean/auto_approve (None) | E08/escalate | 0.81 | Invoice supplier 'Asdown Catering Ltd' vs PO supplier 'Ashdown Catering Ltd' (similarity 0.97) |
| DOC-0051 | clean/auto_approve (None) | unclassified/escalate | 0.67 | Line 1: 787 x £14.88 != £2782.56 |

## Caveats

- The synthetic data was generated with the same rules the agent applies, so rule-based steps are expected to score near 100%. Real invoices will be messier. These results are an upper bound for the deterministic steps and a regression baseline, not a production accuracy estimate.
- Extraction was simulated, not performed by a model. The simulation tests the safeguards around extraction, not extraction quality itself.
- Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.
