# Product Requirements Document

InvoiceAgent — an agentic AI system for invoice reconciliation.
Author: Aditya · Version 1.1 · Status: built through the evaluation step

> Version 1.1 records what was actually built. The problem, vision, users and scope are
> unchanged from v1.0. Where the build contradicted the original document, it is marked
> **[changed in v1.1]** with a link to the decision. See [Changes since v1.0](#9-changes-since-v10).

## 1. Problem statement

Accounts Payable teams in large enterprises process thousands of invoices monthly against purchase
orders. Industry benchmarks indicate that 20–40% of invoices fail automated three-way matching
(invoice to PO to goods receipt) and land on an AP analyst's desk as exceptions. These analysts
spend the majority of their time on mechanical detective work: identifying which PO an invoice
belongs to, diagnosing why amounts differ, flagging duplicates, and routing issues to the right
resolver.

Existing AP automation (SAP, Coupa, Oracle) handles clean matches well through deterministic rules.
What it handles poorly is the fuzzy middle: invoices with slightly incorrect PO references, amounts
that differ for legitimate reasons (partial deliveries, agreed price adjustments, currency
rounding), or invoices where no PO was ever raised. This fuzzy middle is where analyst time
concentrates and where errors are most costly.

The cost of getting this wrong is asymmetric. Wrongly approving a fraudulent or duplicate invoice
results in direct financial loss. Wrongly escalating a clean invoice wastes analyst time but causes
no financial harm. Any AI system operating in this space must be calibrated for this asymmetry.

## 2. Product vision

InvoiceAgent automates exception triage and resolution in invoice reconciliation. It extracts
structured data from invoices, matches them against purchase orders and goods receipts, diagnoses
the root cause of mismatches, and either resolves exceptions autonomously (within defined
boundaries) or escalates them with a structured brief for human review.

The agent reasons across documents, explains its findings with evidence links, and learns from
analyst overrides to improve over time. It is designed to augment AP analysts by removing
mechanical work, not to replace their judgement on ambiguous cases.

## 3. Users and personas

**AP Analyst (primary user).** Processes 80–150 invoices per day, of which 20–50 are exceptions.
Uses SAP/ERP plus spreadsheets to track exception resolution. Pain: repetitive diagnosis work; the
same exception types recur but each requires manual investigation. Goal: spend time on genuinely
ambiguous cases. Fear: being held accountable for an error the agent made autonomously.

**AP Manager (oversight user).** Manages 5–10 analysts; accountable for processing SLAs and error
rates. Pain: no visibility into exception patterns, and no easy way to spot systemic supplier
issues. Goal: reduce cost per invoice while maintaining or improving accuracy. Fear: audit findings
about auto-approved invoices.

**Finance Controller (sponsor).** Accountable for financial controls and SOX compliance. Will not
approve any system that weakens the control environment. Needs a clear audit trail: what was
auto-approved, why, and what the agent's confidence was.

## 4. Scope

**In scope (MVP).** Structured data extraction from invoices (PDF and structured formats);
three-way matching against POs and goods receipts; exception classification with confidence scores;
auto-resolution for high-confidence, low-risk exceptions within tolerance; structured escalation
briefs; a decision audit trail for every invoice; analyst override capture with reason codes.

**Out of scope (v1).** ERP integration (the agent works on uploaded batches); payment execution
(the agent recommends, it does not pay); supplier communication; multi-currency conversion; fraud
detection beyond duplicate identification.

## 5. User stories

| ID | Story | Where it is implemented |
|---|---|---|
| US-01 | As an AP analyst, I want to upload a batch of invoices and POs so the agent can identify which invoices match cleanly and which need my attention. | `POST /batches`, batch setup screen |
| US-02 | As an AP analyst, I want each exception to include a clear explanation and supporting evidence so I can resolve it without re-investigating. | Escalation brief and evidence panels on the invoice screen |
| US-03 | As an AP analyst, I want to override the agent's classification with a reason code so the system learns from my corrections. | Review panel; `POST …/review`; `var/reviews.jsonl` |
| US-04 | As an AP manager, I want a summary dashboard of exception volumes, auto-resolution rate and override rate. | Dashboard screen; `GET …/dashboard` |
| US-05 | As a finance controller, I want a complete audit trail of every auto-approved invoice, including reasoning and confidence. | Audit record on each invoice; CSV export |
| US-06 | As an AP analyst, I want the agent to flag when it is uncertain rather than guessing. | Confidence thresholds; anything uncertain escalates |

## 6. Success metrics

### Product metrics (primary)

| Metric | Baseline (manual) | Target | Measurement | Status |
|---|---|---|---|---|
| Exception resolution time | 15–25 min | < 5 min (human review cases) | Median time from flagged to resolved | Not measured (needs analysts using it) |
| Auto-resolution rate | 0% | 40–60% of exceptions | % resolved without human touch | **32.5% — ceiling, see [D-01 addendum](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold)** |
| False approval rate | n/a | < 0.5% | % of auto-approved invoices later found incorrect | 0% on synthetic data, including under simulated misreads |
| Analyst override rate | n/a | < 15% | % of classifications changed by an analyst | Not measured (needs analysts) |
| Processing cost per invoice | to be measured | 30–50% reduction | AP labour cost / invoices | Not measured |

### Model metrics (secondary, internal)

| Metric | Target | Status |
|---|---|---|
| Extraction accuracy (field level) | > 95% | Not measured (needs the live run) |
| Match accuracy (PO identification) | > 98% | 100% on synthetic data |
| Exception classification accuracy | > 90% | 100% on synthetic data |
| Confidence calibration | within 5% | 14.5% as-is; 0.4% after fitting — see [evaluation framework](evaluation-framework.md#calibration) |

Full results and caveats: [eval/results/SUMMARY.md](../eval/results/SUMMARY.md).

## 7. Prioritisation rationale

The four modes are prioritised by value to the primary user:

- **P0 — Single invoice scoring and exception triage.** The core product. If this does not work,
  nothing else matters. *Built.*
- **P1 — Batch processing with summary dashboard.** The workflow AP teams actually use, and the
  manager's visibility. *Built.*
- **P2 — Override capture and feedback loop.** Without this the agent cannot improve and analysts
  will not trust it. *Capture built; the learning loop that uses it is not.*
- **P3 — Audit trail export.** Essential for production, not for demonstrating product value.
  *Built as JSON and CSV export.*

## 8. What is not built

- **Live evaluation at full scale.** The protocol requires a run over all 500 invoice documents with
  the shipping model. Only a 27-invoice pilot on an alternative model has been run, so accuracy at
  volume, latency and cost on Claude remain projections.
- **Cached responses for demo mode**, beyond the 27 invoices the pilot recorded.
- **The learning half of the feedback loop.** Overrides are captured with reason codes and
  reported, but nothing yet feeds them back into the agent's behaviour.
- **Persistence.** Batches live in memory; only reviews are written to disk.

## 9. Changes since v1.0

| Change | Why | Decision |
|---|---|---|
| Auto-resolution target is unreachable as specified | D-01 allows only E01 and E04 to be auto-resolved, which caps the rate at 32.5% of the exception mix in §2.3 | [D-01 addendum](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold) |
| E03 and E07 are always escalated | §2.2 called them "conditionally" auto-resolvable, which contradicts D-01 | [D-01 addendum](decision-log.md#d-01-autonomy-boundary-set-at-a-conservative-threshold) |
| E01 test data is generated inside the tolerance | §2.3's 0.1–2% variance overlaps D-02's limit, so some invoices would be labelled E01 but are E02 by rule | [D-07](decision-log.md#d-07-test-data-follows-the-rules-not-the-data-spec-where-they-conflict) |
| 501 POs and 476 goods receipts, not 200 each | Every invoice bills one whole PO, so the invoice mix sets the PO count | [D-07](decision-log.md#d-07-test-data-follows-the-rules-not-the-data-spec-where-they-conflict) |
| Supplier-name boundary defined | §2.1 calls typos "minor variation"; §2.3 lists them under E08 | [D-08](decision-log.md#d-08-where-a-supplier-name-difference-becomes-e08) |
| Two new duplicate-detection rules | The evaluation found two ways a supplier could be paid twice | [D-09](decision-log.md#d-09-invoices-awaiting-manual-entry-stay-in-the-duplicate-check-history), [D-10](decision-log.md#d-10-the-same-po-billed-twice-for-the-same-amount-is-a-duplicate-signal-on-any-date) |
| Reviews and overrides are distinct | Confirming an escalation is not a correction, and counting it as one would distort the override metric | [D-12](decision-log.md#d-12-confirming-an-escalation-is-a-review-not-an-override) |
