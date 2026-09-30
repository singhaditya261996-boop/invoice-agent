# Synthetic data generator

Generates the labelled evaluation set described in PRD §2.3.

```bash
python -m data.generator.generate            # seed 42 -> data/synthetic/
python -m data.generator.generate --seed 7 --out /tmp/alt
```

## Output (`data/synthetic/`)

| File | Contents |
|---|---|
| `invoices.json` | 500 invoices in batch processing order, each wrapped as `{doc_id, invoice}` |
| `purchase_orders.json` | All POs, including 36 with no invoice (decoys and unbilled orders) |
| `goods_receipts.json` | At most one GR per PO |
| `ground_truth.json` | Per invoice: exception code, expected action, true PO (or `null`), duplicate original, sub-scenario variant, edge-case tags |
| `manifest.json` | Seed, counts by code / action / variant / edge case, and the assumptions used |

Output is deterministic for a given seed. `tests/test_generator.py` checks that every
invoice shows the discrepancy its label claims **and no other**. It also fails if the
committed data drifts from the generator.

## Scenario mix

Invoice counts match the PRD exactly. Each bucket has sub-variants so the agent is tested on
more than one form of each exception:

| Code | Count | Variants |
|---|---|---|
| clean | 300 | 255 plain · 25 benign name variants (`Ltd`→`Limited`) · 10 PO-ref format variants (`PO2026004817`) · 10 recurring monthly retainers |
| E01 | 40 | unit-price adjustment, within tolerance |
| E02 | 25 | 3–15% pricing error (10 with no GR on file) |
| E03 | 30 | 25 structured short delivery · 5 shortfall recorded only in GR free-text notes |
| E04 | 25 | resubmission of a clean invoice: same number, shifted date, or renumbered (`-R`, `/1`, `A`) |
| E05 | 30 | 8 missing ref · 12 corrupted ref (truncated, transposed, wrong year, dropped digit) · 10 maverick spend (no PO exists) |
| E06 | 15 | late invoice against a closed PO |
| E07 | 20 | 10 wrong VAT rate (0/5/15/17.5%) · 10 header miscalculation |
| E08 | 15 | initialism, subsidiary, parent group, trading name, 2-character typo |

**Edge cases** (PRD §5.1) are tagged in `edge_cases` so evaluation can report on them separately:

- **Traps that should not be flagged:** benign name variants must not become E08; PO-ref
  formatting must not become E05; recurring retainers must not become E04.
- **Genuinely ambiguous cases:**
  - E05 invoices whose true PO has a near-identical competing PO (`ambiguous_candidates`).
  - E03 shortfalls visible only in free-text GR notes (`gr_notes_only`).
  - E08 typos (`ambiguous_name_typo`).

## Deviations from the PRD

1. **PO and GR counts are higher than PRD §2.3 (501 / 476, not 200 / 200).** E01 and E02 are
   defined as invoice total vs. PO total, so every invoice must bill one whole PO. That needs
   about 470 invoiced POs. Another 36 POs have no invoice and add noise for fuzzy matching.
2. **E01 variance is kept inside the D-02 tolerance.** It is not the "0.1–2%" in §2.3. With
   the tolerance at 1% or £50, whichever is smaller, anything over 1% (or over £50) is E02 by
   definition. Following §2.3 would mislabel some invoices.
3. **Where "minor variation" ends and E08 begins.** §2.1 says an invoice supplier name "may
   differ slightly (Ltd, plc, typos)". §2.3, however, lists typos and abbreviations under E08.
   The line drawn here:
   - Legal-suffix and formatting changes are **clean**.
   - Initialisms, related entities (subsidiary or parent), trading names and typos of two or
     more characters are **E08**.
   - One-character typos are not generated, because their correct label is unclear.

## Conventions the pipeline must follow

- The amount check compares invoice **subtotal** (pre-tax) with PO `total_amount` (pre-tax).
- An invoice line's `total` is net (`quantity × unit_price`). VAT is rounded per line, and the
  header tax is the sum of the line taxes.
- E07 errors are always at least £1. Clean invoices match to the penny, and
  `tax_rounding_tolerance` (£0.05) covers rounding done a different way.
- All tax is standard-rated at 20%. Zero-rated and exempt items are not modelled.
- Invoices are JSON only. Extraction accuracy (§5.2) needs rendered documents (PDF/text) to
  extract from, which is not in scope here.
