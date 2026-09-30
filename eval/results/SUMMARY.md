# Evaluation summary

Status: **partial.** The PRD protocol (§5.3) calls for a live run on all 500 invoice documents with
the shipping model. That has not been done. What exists: a rules-only baseline over all 500, a cost
projection, simulated extraction errors, and a 19-invoice live pilot on an alternative model
(Gemini 3 Flash, free tier) that exercises real document extraction end to end.

Per-run reports: `<run>/report.md`. Machine-readable metrics: `<run>/metrics.json`.

## Runs

| Run | What it tests | Classification | Auto-approve precision | Escalation recall | Auto-resolution rate | Straight-through |
|---|---|---|---|---|---|---|
| `offline-structured` | Match, validate, classify on structured invoices (no LLM) | 100% | 100% | 100% | 32.5% | 73.0% |
| `simulated-perfect-extraction` | Same, from documents, with extraction answered correctly | 100% | 100% | 100% | 12.5% | 63.0% |
| `simulated-errors-0.3-documents` | 30% of invoices have one field misread, at 95% stated confidence | 78.0% | 100% | 100% | 6.2% | 46.6% |
| `simulated-errors-1-documents` | Every invoice has one field misread | 28.4% | 100% | 100% | 0.5% | 13.8% |
| `live-gemini3-documents-n8` | First live pilot, 11 invoices, Gemini 3 Flash | 90.9% | 100% | 100% | 42.9% | 54.5% |
| `live-gemini3-documents-n19` | **Real extraction**, 19 invoices, same model, extends the above | 94.7% | 100% | 100% | 26.7% | 36.8% |

PRD targets: classification > 90%, auto-approve precision > 99.5%, escalation recall > 99%,
auto-resolution 40–60%. Classification accuracy is expected to fall when fields are misread,
because the agent is then looking at a different invoice. What matters is that none of those
invoices is paid wrongly.

## The live pilot (19 invoices, Gemini 3 Flash, £0)

Run over two sittings, ten days apart, because the free tier allows 20 requests per model per day.
The second run replayed the first run's recorded responses (`--reuse-recorded`) and spent its quota
only on invoices not yet measured, so the samples combine into one.

- **Field accuracy was 100% on every invoice the model actually read** (18 of 19). Both runs lost
  exactly one invoice to the daily quota, and both times the agent sent it to manual entry rather
  than guessing — graceful degradation observed against a real API rather than a stub.
- **Action accuracy was 100% while classification was 94.7%.** The single classification miss is the
  quota-stopped invoice: unreadable, so unclassified, so escalated — which was the correct action
  anyway. The failure mode costs an analyst two minutes and cannot cost money.
- **Median latency 23.8 s**, inside the 30 s target, measured on the five invoices whose calls ran
  fresh in the second sitting. The first sitting measured 42.9 s on eleven. Both are real; the
  spread on samples this size is wide.
- **Calibration error 6.6%** against the < 5% target, now measured on real errors rather than none.
- **Auto-resolution rate is not worth quoting at this size**: 42.9% on the first sample, 26.7% on
  the larger one, entirely driven by which exception types the stratified sample happened to draw.
- The 37 recorded responses are the demo-mode fixtures, so the UI replays real model output for
  these 19 invoices with no API key.

**These numbers describe Gemini 3 Flash, not the model this product would ship with.** They show
the pipeline works end to end against a real API; they are not a substitute for the Claude run.

## Findings

1. **No false approvals under any condition tested.** With misreads injected into up to 100% of
   invoices, every misread that affects payment (369 of 369) was stopped, either by the extraction
   arithmetic checks (manual entry) or by the three-way match (escalation).

2. **The evaluation found and fixed two double-payment paths.** Both were found by the
   extraction-error simulation and are now covered by regression tests:
   - A duplicate of an invoice that had gone to manual entry was approved, because unverified
     invoices were kept out of the duplicate-check history. They are now kept, and any strong
     link to one (supplier plus invoice number, PO reference, or amount) escalates.
   - A duplicate was approved when a misread date moved it outside the ±1-day window. The same PO
     billed again for the same amount is now flagged on any date, and escalated rather than rejected.

3. **Auto-resolution misses the PRD target, for two separate reasons.**
   - *By design (D-01):* only E01 and E04 may be auto-resolved. In the PRD's own mix that caps
     the rate at 65 of 200 exceptions, **32.5%**, even for a perfect agent.
   - *Double-counted extraction risk:* extraction confidence is multiplied into classification
     confidence. At 95% stated extraction confidence, no E01 reaches the 95% auto-approve bar, so
     documents give 12.5% where structured input gives 32.5%. The simulations show the extraction
     safeguards catch misreads without that penalty. Calibration (D-04), fitted on the live run,
     is the intended correction.

4. **Calibration misses the < 5% target before fitting (14.5%) and meets it after (0.4%, cross-fitted).**
   The agent is under-confident: every confidence bucket is 100% accurate on this data. No
   calibration table is installed yet, because fitting on rules-generated data would push every
   score to about 99.7% and erase the uncertainty signal on genuinely ambiguous cases (for example
   the GR-notes-only E03s, currently amber). It should be fitted on the live run.

5. **Cost is projected well inside target.** $6.79–$32.65 for 500 documents on `claude-opus-5` at
   medium effort, which is £0.011–£0.052 per invoice (target < £0.15). The range is mostly unknown
   thinking-token spend. On structured input only briefs and GR notes use the LLM: $2.19–$8.30.

## Not yet measured (needs a full run on the shipping model)

The pilot above covers extraction, GR-notes reading and brief writing on 19 invoices with Gemini 3
Flash. Outstanding:

- Extraction accuracy at volume, on the model this product would ship with (target > 95%)
- Latency and cost on that model (the pilot's 42.9 s median is a preview model's)
- A calibration table fitted on its errors

```bash
python -m eval.run_eval --mode live --input documents --limit 40 --max-cost-usd 5   # pilot, about $1-3
python -m eval.run_eval --mode live --input documents --max-cost-usd 40 --fit-calibration
```

## Caveat

The synthetic data was generated from the same rules the agent applies, so rule-based steps score
near 100% by construction. These numbers are a regression baseline and a safety test of the
guardrails, not an estimate of production accuracy on real invoices.
