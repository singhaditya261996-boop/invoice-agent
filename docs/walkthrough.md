# One invoice, end to end

What the agent actually does, traced through a single real invoice from the evaluation set. Every
value below is copied from the run record (`eval/results/live-gemini3-documents-n27/results.jsonl`,
document `DOC-0003`) — nothing here is illustrative.

You can open this invoice in the [live demo](https://singhaditya261996-boop.github.io/invoice-agent/).

## What arrives

A text document. No structured data, no guarantee the PO reference is right, no guarantee the
numbers are internally consistent.

```
Harrowgate Stationery Co Ltd
TAX INVOICE

Invoice No:    000884
Invoice Date:  26/07/2026
Due Date:      25/08/2026
Customer PO:   PO-2026-943012
Bill To:       Aldermoor Group plc, Accounts Payable, 14 Canal Street, Leeds LS1 4AB

Description                                     Qty  Unit Price         VAT          Net
----------------------------------------------------------------------------------------
Envelopes C4 self-seal, box of 250               30      £33.26     £199.56      £997.80
----------------------------------------------------------------------------------------
                                                                  Subtotal       £997.80
                                                                       VAT       £199.56
                                                                 TOTAL DUE     £1,197.36

Payment terms: Net 30. Please quote the invoice number.
```

## Step 1 — Extract *(model)*

The model returns the fields as printed, told explicitly **not** to correct anything: if the VAT on
the document is wrong, it must come back wrong, because the downstream checks exist to catch that.

| Field | Value |
|---|---|
| invoice_number | `000884` |
| supplier_name | `Harrowgate Stationery Co Ltd` |
| po_reference | `PO-2026-943012` |
| invoice_date | `2026-07-26` |
| subtotal / VAT / total | `997.80` / `199.56` / `1197.36` |
| line | `Envelopes C4 self-seal, box of 250` — qty `30` @ `33.26` = `997.80` |

The agent then checks arithmetic the document must satisfy regardless of any tax error: each line's
quantity × unit price equals its total, the lines sum to the subtotal, and subtotal + VAT equals the
total. All three hold, so confidence stays at **1.00** and the invoice proceeds. Had any failed, the
confidence would have been multiplied by 0.7 per failure and the invoice sent to manual entry rather
than matched on numbers that may be misread.

## Step 2 — Match *(rules)*

`PO-2026-943012` exists, so it is an exact match, **score 1.00**. No fuzzy search needed.

Had the reference been missing or wrong, the agent would have searched by supplier, amount within
10% and order date within 90 days, and accepted a candidate only at a score of 0.95 or better *and*
a clear lead over the runner-up — otherwise it escalates with the candidates listed rather than
guessing.

## Step 3 — Validate *(rules, plus the model for free text)*

Eight checks ran. Seven passed:

- PO status: Partially Fulfilled
- Supplier name matches the PO exactly
- Subtotal £997.80 equals the PO total
- Goods receipt GR-2026-774584 on file, received 2026-07-13 by E. Lindqvist
- GR notes *"Partial delivery: 7 x Envelopes C4 self-seal, box of 250 on backorder"* read by the AI model → shortfall reported
- VAT £199.56 matches recalculation at 20%
- No prior invoice from this supplier for £1,197.36 within ±1 day, or with the same invoice number

One failed:

> **Envelopes C4 self-seal, box of 250: invoiced 30, goods receipt shows 23 received**

Note what the amount check alone would have concluded: the invoice total matches the PO total
exactly, so a two-way match would have passed this invoice and paid for seven boxes that never
arrived. The goods receipt is what catches it.

The free-text note is the one place the model is used here beyond extraction. It agrees with the
structured quantities, which is the easy case. When the note and the structured data *disagree* —
the note describes a shortfall the quantities don't show — the agent escalates rather than picking
one, because that conflict is exactly where an automated guess would be most expensive.

## Step 4 — Classify *(rules)*

One discrepancy, one clear category: **E03, quantity variance**, confidence **0.95**, band green.

Confidence here is the evidence strength of the finding (0.95 for a structured quantity mismatch)
multiplied by the match score (1.00) and the extraction confidence (1.00).

The action is **escalate** — and this is the part worth pausing on. Confidence is high, the finding
is unambiguous, and the agent still does not act. E03 is outside the autonomy boundary
([D-01](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold)): only clean
invoices, amounts within tolerance, and clear duplicates are resolved without a human. The autonomy
rules run *after* classification and cannot be overridden by the model.

## Step 5 — Report *(model writes the prose, rules supply the figures)*

> **Summary.** Invoice 000884 from Harrowgate Stationery Co Ltd shows a quantity variance where 30
> boxes were invoiced but only 23 were received.
>
> **What I could not resolve.** I found a discrepancy between the 30 boxes of C4 self-seal envelopes
> invoiced and the 23 units recorded on goods receipt GR-2026-774584. Notes from E. Lindqvist
> indicate that 7 units are on backorder, leaving the purchase order partially fulfilled.
>
> **Recommended action.** Confirm the quantity received with E. Lindqvist and pay only for the 23
> items delivered. Hold the remaining balance until the backordered items are received and booked
> into the system.

Every figure in that brief — 30, 23, the PO number, the GR number, the receiver's name — came from
the deterministic checks and was handed to the model as facts. The model chose the wording. It is
not permitted to produce the numbers, so it cannot invent one.

The analyst gets this with the full check list, the evidence links, and a one-click decision. If
they disagree, a reason code is required and recorded
([D-05](decision-log.md#d-05-override-reasons-are-structured-not-free-text)).

## What is recorded

Every invoice leaves an audit record (US-05): the extracted fields and confidence, the match method
and score, every check performed, every discrepancy with its evidence strength, the raw and
calibrated confidence, each model call with its token counts, and the analyst's eventual decision.
For this invoice, three model calls: extraction, the GR note, and the brief.

## What would have changed the outcome

| If | Then |
|---|---|
| The amount differed by less than 1% or £50 | E01, and auto-approved at ≥ 95% confidence |
| The amount differed by more | E02, escalated — no confidence level permits auto-approval |
| The shortfall appeared **only** in the note, not the quantities | Still E03, but confidence 0.85 and amber: a conflict between sources, not a fact |
| An invoice for the same amount from this supplier had already been processed | E04, auto-rejected at ≥ 85% confidence |
| The arithmetic on the document hadn't held | Manual data entry, no classification, no decision |

The through-line: the agent acts on its own only where the evidence is unambiguous *and* the cost of
being wrong is low. Everything else arrives on a human's desk with the work already done.
