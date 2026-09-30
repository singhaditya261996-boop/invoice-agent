import { useState, type ReactNode } from "react";

import {
  api, type Code, type Decision, type GoodsReceipt, type InvoiceResult, type OverrideReason, type PurchaseOrder,
  type Review,
} from "../api";
import {
  ActionBadge, Button, Card, CodeBadge, ConfidenceBadge, Drawer, ErrorNote, Field, inputClass, Loading,
} from "../components/ui";
import { CODE_LABELS, codeLabel, date, DECISION_LABELS, gbp, pct, REASON_LABELS } from "../format";
import { href, useAsync, useStoredState } from "../hooks";

type Evidence = { kind: "source" } | { kind: "po"; po: string } | { kind: "gr"; po: string };

export function InvoicePage({ batchId, docId }: { batchId: string; docId: string }) {
  const detail = useAsync(() => api.result(batchId, docId), [batchId, docId]);
  const [evidence, setEvidence] = useState<Evidence | null>(null);

  if (detail.error) return <ErrorNote message={detail.error} />;
  if (!detail.data) return <Loading />;
  const { result: r, review } = detail.data;
  const inv = r.extraction.invoice;
  const po = r.match?.matched_po ?? null;
  const gr = r.validation?.goods_receipt ?? null;

  return (
    <div className="space-y-5">
      <div>
        <a href={href("batches", batchId)} className="text-sm text-ink-2 hover:text-ink">← Review queue</a>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Invoice {r.invoice_number ?? docId}</h1>
            <p className="mt-1 text-sm text-ink-2">
              {inv ? <>{inv.supplier_name} · {gbp(inv.total_amount)} · dated {date(inv.invoice_date)}</> : "Not extracted"}
              <span className="text-muted"> · {docId}</span>
            </p>
          </div>
          <Button variant="secondary" onClick={() => setEvidence({ kind: "source" })}>View source invoice</Button>
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Decision r={r} />
          {r.brief ? <BriefView r={r} onEvidence={setEvidence} /> : <ApprovalReasons r={r} />}
          {inv && <Comparison r={r} po={po} gr={gr} onEvidence={setEvidence} />}
          <AuditDetails r={r} />
        </div>
        <div className="lg:sticky lg:top-6">
          <ReviewPanel batchId={batchId} r={r} review={review} onSaved={detail.reload} />
        </div>
      </div>

      {evidence && <EvidenceDrawer batchId={batchId} docId={docId} evidence={evidence} onClose={() => setEvidence(null)} />}
    </div>
  );
}

// ------------------------------------------------------------------------ decision

const ACTION_SENTENCE = {
  auto_approve: "I approved this invoice for payment.",
  auto_reject: "I rejected this invoice.",
  escalate: "I need you to review this invoice.",
};

function Decision({ r }: { r: InvoiceResult }) {
  const c = r.classification;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <ActionBadge action={c.action} />
        <CodeBadge code={c.code} withLabel />
        <span className="ml-auto"><ConfidenceBadge confidence={c.confidence} band={c.band} size="lg" /></span>
      </div>
      <p className="mt-4 text-lg font-medium">{ACTION_SENTENCE[c.action]}</p>
      <p className="mt-1 text-sm text-ink-2">{r.brief?.summary ?? c.rationale}</p>
      {c.used_llm && <p className="mt-2 text-xs text-muted">The root cause was chosen by the AI model; the action by
        fixed rules.</p>}
    </Card>
  );
}

// ------------------------------------------------------------------------ brief (trust design §7.2)

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </div>
  );
}

function BriefView({ r, onEvidence }: { r: InvoiceResult; onEvidence: (e: Evidence) => void }) {
  const b = r.brief!;
  const po = r.match?.matched_po;
  return (
    <Card title="Escalation brief">
      <div className="space-y-5 text-sm leading-relaxed">
        <Section title="What I found">
          <ul className="space-y-1.5">
            {b.what_i_found.map((f, i) => (
              <li key={i} className="flex gap-2"><span aria-hidden className="text-critical-ink">≠</span>{f}</li>
            ))}
          </ul>
        </Section>
        <Section title="What I could not resolve"><p>{b.what_i_could_not_resolve}</p></Section>
        <Section title="Recommended action">
          <p className="rounded-lg bg-accent-soft/40 px-3 py-2 font-medium">{b.recommended_action}</p>
        </Section>
        <Section title="What I checked"><Checklist items={b.what_i_checked} /></Section>
        <Section title="Evidence">
          <div className="flex flex-wrap gap-2">
            <EvidenceLink onClick={() => onEvidence({ kind: "source" })}>Source invoice</EvidenceLink>
            {po && <EvidenceLink onClick={() => onEvidence({ kind: "po", po: po.po_number })}>{po.po_number}</EvidenceLink>}
            {r.validation?.goods_receipt && po && (
              <EvidenceLink onClick={() => onEvidence({ kind: "gr", po: po.po_number })}>
                {r.validation.goods_receipt.gr_number}</EvidenceLink>
            )}
            {r.match?.candidates.filter((c) => c.po_number !== po?.po_number).map((c) => (
              <EvidenceLink key={c.po_number} onClick={() => onEvidence({ kind: "po", po: c.po_number })}>
                Candidate {c.po_number} ({c.score.toFixed(2)})</EvidenceLink>
            ))}
            {b.evidence.filter((e) => e.startsWith("Prior invoice")).map((e) => (
              <span key={e} className="rounded-md bg-wash px-2 py-1 text-xs text-ink-2">{e}</span>
            ))}
          </div>
        </Section>
      </div>
    </Card>
  );
}

function EvidenceLink({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className="rounded-md border border-line bg-raised px-2 py-1 text-xs font-medium
      hover:bg-wash">
      {children} →
    </button>
  );
}

function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1">
      {items.map((c, i) => (
        <li key={i} className="flex gap-2 text-ink-2"><span aria-hidden className="text-good-ink">✓</span>{c}</li>
      ))}
    </ul>
  );
}

function ApprovalReasons({ r }: { r: InvoiceResult }) {
  return (
    <Card title="Why I approved it">
      <div className="space-y-4 text-sm">
        <p>{r.classification.rationale}</p>
        {r.validation && <Checklist items={r.validation.checks_performed} />}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------------ side-by-side comparison

const key = (s: string) => s.toLowerCase().replace(/[^\w\s]/g, " ").replace(/\s+/g, " ").trim();

function Cell({ value, mismatch, className = "" }: { value: ReactNode; mismatch?: boolean; className?: string }) {
  return (
    <td className={`tabular px-3 py-2 text-right ${mismatch ? "bg-warning/15 font-semibold" : ""} ${className}`}>
      {mismatch && <span aria-label="does not match" className="mr-1 text-critical-ink">≠</span>}
      {value}
    </td>
  );
}

function Comparison({ r, po, gr, onEvidence }: {
  r: InvoiceResult; po: PurchaseOrder | null; gr: GoodsReceipt | null; onEvidence: (e: Evidence) => void;
}) {
  const inv = r.extraction.invoice!;
  const poLines = new Map(po?.line_items.map((l) => [key(l.description), l]));
  const grLines = new Map(gr?.line_items.map((l) => [key(l.description), l]));
  const nameMismatch = po && inv.supplier_name !== po.supplier_name;
  return (
    <Card title="Invoice against purchase order and goods receipt"
      action={po && <button className="text-xs text-accent hover:underline"
        onClick={() => onEvidence({ kind: "po", po: po.po_number })}>Open PO</button>}>
      <dl className="mb-5 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Fact label="PO quoted on invoice" value={inv.po_reference || <span className="text-muted">none</span>} />
        <Fact label="Matched PO" value={po ? `${po.po_number} (${matchLabel(r)})` : <span className="text-muted">none</span>} />
        <Fact label="Supplier on invoice" value={inv.supplier_name} flag={!!nameMismatch} />
        <Fact label="Supplier on PO" value={po?.supplier_name ?? "—"} />
        {po && <Fact label="PO status" value={po.status} flag={po.status === "Closed"} />}
        {po && <Fact label="Approver · cost centre" value={`${po.approver} · ${po.cost_centre}`} />}
        {gr && <Fact label="Goods received" value={`${date(gr.receipt_date)} by ${gr.receiver}`} />}
        {gr?.notes && <Fact label="Receiving notes" value={`“${gr.notes}”`} />}
      </dl>
      <div className="-mx-5 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-y border-line">
              <th className="px-5 py-2 text-left font-medium">Line</th>
              <th className="px-3 py-2 text-right font-medium">Invoiced</th>
              <th className="px-3 py-2 text-right font-medium">Ordered</th>
              <th className="px-3 py-2 text-right font-medium">Received</th>
              <th className="px-3 py-2 text-right font-medium">Unit price</th>
              <th className="px-3 py-2 text-right font-medium">PO price</th>
              <th className="px-5 py-2 text-right font-medium">Net</th>
            </tr>
          </thead>
          <tbody>
            {inv.line_items.map((l, i) => {
              const p = poLines.get(key(l.description));
              const g = grLines.get(key(l.description));
              return (
                <tr key={i} className="border-b border-line">
                  <td className="px-5 py-2">{l.description}{!p && po && <span className="ml-1 text-xs text-critical-ink">
                    (not on PO)</span>}</td>
                  <Cell value={Number(l.quantity)} />
                  <Cell value={p ? Number(p.quantity) : "—"} mismatch={!!p && Number(p.quantity) !== Number(l.quantity)} />
                  <Cell value={g ? Number(g.quantity_received) : "—"}
                    mismatch={!!g && Number(g.quantity_received) < Number(l.quantity)} />
                  <Cell value={gbp(l.unit_price)} />
                  <Cell value={p ? gbp(p.unit_price) : "—"} mismatch={!!p && p.unit_price !== l.unit_price} />
                  <Cell value={gbp(l.total)} className="pr-5" />
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td className="px-5 py-2 font-medium" colSpan={5}>Subtotal (PO total {po ? gbp(po.total_amount) : "—"})</td>
              <td />
              <Cell value={gbp(inv.subtotal)} mismatch={!!po && Number(po.total_amount) !== Number(inv.subtotal)}
                className="pr-5 font-medium" />
            </tr>
            <tr>
              <td className="px-5 py-1 text-ink-2" colSpan={6}>VAT</td>
              <Cell value={gbp(inv.tax_amount)} mismatch={r.validation?.discrepancies.some((d) => d.check === "tax")}
                className="pr-5" />
            </tr>
            <tr className="border-t border-line">
              <td className="px-5 py-2 font-semibold" colSpan={6}>Total</td>
              <Cell value={gbp(inv.total_amount)} className="pr-5 font-semibold" />
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

function matchLabel(r: InvoiceResult): string {
  const m = r.match!;
  return { exact: "exact reference", exact_normalized: "same number, different format",
    fuzzy: `inferred, score ${m.score.toFixed(2)}`, none: "none" }[m.method] ?? m.method;
}

function Fact({ label, value, flag }: { label: string; value: ReactNode; flag?: boolean }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line py-1 sm:block sm:border-0 sm:py-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={flag ? "font-semibold" : ""}>
        {flag && <span aria-label="does not match" className="mr-1 text-critical-ink">≠</span>}{value}
      </dd>
    </div>
  );
}

// ------------------------------------------------------------------------ audit trail (US-05)

function AuditDetails({ r }: { r: InvoiceResult }) {
  const c = r.classification;
  return (
    <details className="rounded-xl border border-line bg-surface px-5 py-3 text-sm">
      <summary className="cursor-pointer font-semibold">Audit record</summary>
      <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Fact label="Processed" value={new Date(r.processed_at).toLocaleString("en-GB")} />
        <Fact label="Mode" value={r.mode} />
        <Fact label="Extraction" value={`${r.extraction.method}, confidence ${pct(r.extraction.confidence)}`} />
        <Fact label="Confidence (raw → calibrated)"
          value={`${c.raw_confidence !== null ? pct(c.raw_confidence, 1) : "—"} → ${pct(c.confidence, 1)}`} />
        <Fact label="Processing time" value={`${r.latency_ms} ms`} />
        <Fact label="Rationale" value={c.rationale} />
      </dl>
      {r.llm_calls.length > 0 && (
        <table className="mt-4 w-full text-xs">
          <thead className="text-left text-muted"><tr><th className="py-1 font-medium">AI model call</th>
            <th className="font-medium">Model</th><th className="text-right font-medium">Tokens in/out</th>
            <th className="pl-3 font-medium">Result</th></tr></thead>
          <tbody>
            {r.llm_calls.map((call, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1">{call.step}</td><td>{call.model}</td>
                <td className="tabular text-right">{call.input_tokens}/{call.output_tokens}</td>
                <td className="pl-3 text-ink-2">{call.error ? `rules used (${call.error})` : call.cached ? "cached" : "ok"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

// ------------------------------------------------------------------------ analyst review (US-03, D-05)

function ReviewPanel({ batchId, r, review, onSaved }: {
  batchId: string; r: InvoiceResult; review: Review | null; onSaved: () => void;
}) {
  const c = r.classification;
  const [analyst, setAnalyst] = useStoredState("invoice-agent.analyst", "");
  const [decision, setDecision] = useState<Decision | null>(
    c.action === "auto_approve" ? "approve" : c.action === "auto_reject" ? "reject" : null);
  const [newCode, setNewCode] = useState<Code | "">(c.code ?? "");
  const [reason, setReason] = useState<OverrideReason | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [editing, setEditing] = useState(!review);

  const codeChanged = c.code !== null && newCode !== "" && newCode !== c.code;
  const reverses = (c.action === "auto_approve" && decision !== null && decision !== "approve")
    || (c.action === "auto_reject" && decision !== null && decision !== "reject");
  const isOverride = codeChanged || reverses;
  const canSubmit = decision !== null && analyst.trim() && (!isOverride || reason) && (reason !== "other" || note.trim());

  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await api.review(batchId, r.doc_id, {
        decision: decision!, new_code: newCode || null, reason: isOverride ? reason || null : null,
        note: note.trim() || undefined, analyst: analyst.trim(),
      });
      setEditing(false);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (review && !editing) {
    return (
      <Card title="Your review">
        <div className="space-y-2 text-sm">
          <p className="text-lg font-medium">{DECISION_LABELS[review.decision]}</p>
          <p className="text-ink-2">Classified as {codeLabel(review.new_code)}{review.is_override
            ? ` (changed from ${codeLabel(review.original_code)})` : ""}.</p>
          {review.reason && <p className="text-ink-2">Reason: {REASON_LABELS[review.reason]}</p>}
          {review.note && <p className="rounded-lg bg-wash px-3 py-2">“{review.note}”</p>}
          <p className="text-xs text-muted">{review.analyst} · {new Date(review.created_at).toLocaleString("en-GB")}</p>
          {review.is_override && <p className="text-xs text-muted">Recorded as an override, so it feeds the agent's
            accuracy tracking.</p>}
          <Button variant="secondary" className="mt-2" onClick={() => setEditing(true)}>Change decision</Button>
        </div>
      </Card>
    );
  }

  return (
    <Card title={c.action === "escalate" ? "Your decision" : "Check the agent's decision"}>
      <div className="space-y-4">
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Decision</legend>
          <div className="grid grid-cols-3 gap-2">
            {(["approve", "reject", "hold"] as Decision[]).map((d) => (
              <button key={d} onClick={() => setDecision(d)} aria-pressed={decision === d}
                className={`rounded-lg border px-2 py-2 text-sm font-medium transition ${decision === d
                  ? "border-accent bg-accent text-accent-ink" : "border-line bg-raised hover:bg-wash"}`}>
                {DECISION_LABELS[d]}
              </button>
            ))}
          </div>
        </fieldset>

        <Field label="Exception type" hint="Change only if the agent got the category wrong.">
          <select className={inputClass} value={newCode} onChange={(e) => setNewCode(e.target.value as Code | "")}>
            {c.code === null && <option value="">Not classified</option>}
            {(Object.keys(CODE_LABELS) as Code[]).map((code) => (
              <option key={code} value={code}>{code === "clean" ? "OK" : code} · {CODE_LABELS[code]}
                {code === c.code ? " (agent)" : ""}</option>
            ))}
          </select>
        </Field>

        {isOverride && (
          <Field label="Why are you overriding the agent?"
            hint="Structured reasons show where the agent goes wrong most often (D-05).">
            <select className={inputClass} value={reason} onChange={(e) => setReason(e.target.value as OverrideReason)}>
              <option value="" disabled>Choose a reason</option>
              {(Object.keys(REASON_LABELS) as OverrideReason[]).map((x) => (
                <option key={x} value={x}>{REASON_LABELS[x]}</option>
              ))}
            </select>
          </Field>
        )}

        <Field label={`Note${reason === "other" ? "" : " (optional)"}`}>
          <textarea className={`${inputClass} h-20`} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="Context for the audit trail, e.g. who you confirmed this with" />
        </Field>

        <Field label="Your name">
          <input className={inputClass} value={analyst} onChange={(e) => setAnalyst(e.target.value)} />
        </Field>

        {isOverride && (
          <p className="text-xs text-ink-2">
            <span aria-hidden className="mr-1">ⓘ</span>
            {reverses ? "This reverses a decision the agent made on its own." : "This changes the agent's classification."}
            {" "}It will be recorded as an override.
          </p>
        )}
        {error && <ErrorNote message={error} />}
        <div className="flex gap-2">
          <Button className="flex-1" disabled={!canSubmit || busy} onClick={submit}>
            {busy ? "Saving…" : "Save decision"}
          </Button>
          {review && <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>}
        </div>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------------ evidence (trust design: show your working)

function EvidenceDrawer({ batchId, docId, evidence, onClose }: {
  batchId: string; docId: string; evidence: Evidence; onClose: () => void;
}) {
  const title = evidence.kind === "source" ? "Source invoice" : evidence.kind === "po" ? `Purchase order ${evidence.po}`
    : `Goods receipt for ${evidence.po}`;
  const state = useAsync<unknown>(() => evidence.kind === "source" ? api.source(batchId, docId)
    : evidence.kind === "po" ? api.purchaseOrder(batchId, evidence.po) : api.goodsReceipt(batchId, evidence.po),
  [batchId, docId, JSON.stringify(evidence)]);

  return (
    <Drawer title={title} onClose={onClose}>
      {state.error && <ErrorNote message={state.error} />}
      {!state.data ? <Loading /> : evidence.kind === "source" ? (
        <SourceView source={state.data as { type: string; text: string }} />
      ) : evidence.kind === "po" ? <POView po={state.data as PurchaseOrder} /> : <GRView gr={state.data as GoodsReceipt} />}
    </Drawer>
  );
}

function SourceView({ source }: { source: { type: string; text: string } }) {
  const text = source.type.includes("json") ? JSON.stringify(JSON.parse(source.text), null, 2) : source.text;
  return (
    <>
      <p className="mb-3 text-xs text-muted">
        {source.type.includes("json") ? "Submitted as structured data." : "Submitted as a document, read by the AI model."}
      </p>
      <pre className="overflow-x-auto rounded-lg bg-wash p-4 text-xs leading-relaxed">{text}</pre>
    </>
  );
}

function POView({ po }: { po: PurchaseOrder }) {
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Fact label="Supplier" value={`${po.supplier_name} (${po.supplier_id})`} />
        <Fact label="Status" value={po.status} />
        <Fact label="Ordered" value={date(po.order_date)} />
        <Fact label="Expected delivery" value={date(po.delivery_date)} />
        <Fact label="Approver" value={po.approver} />
        <Fact label="Cost centre" value={po.cost_centre} />
        <Fact label="Payment terms" value={po.payment_terms} />
        <Fact label="Total (ex VAT)" value={gbp(po.total_amount)} />
      </dl>
      <LinesTable rows={po.line_items.map((l) => [l.description, Number(l.quantity), gbp(l.unit_price), gbp(l.total)])}
        head={["Line", "Qty", "Unit price", "Total"]} />
    </div>
  );
}

function GRView({ gr }: { gr: GoodsReceipt }) {
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <Fact label="Receipt" value={gr.gr_number} />
        <Fact label="Received" value={`${date(gr.receipt_date)} by ${gr.receiver}`} />
      </dl>
      {gr.notes && <p className="rounded-lg bg-wash px-3 py-2">Notes: “{gr.notes}”</p>}
      <LinesTable rows={gr.line_items.map((l) => [l.description, Number(l.quantity_received)])}
        head={["Line", "Quantity received"]} />
    </div>
  );
}

function LinesTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-xs text-muted">
        <tr className="border-b border-line">{head.map((h, i) => (
          <th key={h} className={`py-2 font-medium ${i ? "text-right" : "text-left"}`}>{h}</th>))}</tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} className="border-b border-line">
            {row.map((cell, j) => <td key={j} className={`tabular py-2 ${j ? "text-right" : ""}`}>{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
