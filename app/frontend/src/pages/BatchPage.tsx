import { useState } from "react";

import { api, STATIC_DEMO, type Action, type Band, type Code, type ResultFilters } from "../api";
import { BarChart, Stat, StackedBar } from "../components/charts";
import {
  ActionBadge, Button, Card, CodeBadge, ConfidenceBadge, Drawer, ErrorNote, Field, inputBase, inputClass, Loading, Segmented,
} from "../components/ui";
import { ACTION_LABELS, BAND_LABELS, CODE_LABELS, DECISION_LABELS, gbp, MODE_LABELS, pct, REASON_LABELS } from "../format";
import { href, useAsync } from "../hooks";
import { Progress } from "./BatchesPage";

export function BatchPage({ batchId, tab }: { batchId: string; tab: "queue" | "dashboard" }) {
  const batch = useAsync(() => api.batch(batchId), [batchId], (b) => b.status !== "complete");
  const [scoring, setScoring] = useState(false);
  const b = batch.data;

  if (batch.error) return <ErrorNote message={batch.error} />;
  if (!b) return <Loading />;
  const complete = b.status === "complete";

  return (
    <div className="space-y-5">
      <div>
        {!STATIC_DEMO && <a href={href()} className="text-sm text-ink-2 hover:text-ink">← All batches</a>}
        <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{b.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-2">
              <span>{MODE_LABELS[b.mode].label} mode</span>
              <Progress done={b.processed} total={b.total} complete={complete} />
              {b.failed > 0 && <span className="text-critical-ink">{b.failed} failed</span>}
            </div>
          </div>
          <div className="flex gap-2">
            {!STATIC_DEMO && (
              <Button variant="secondary" disabled={!complete} onClick={() => setScoring(true)}
                title={complete ? undefined : "Available once the batch has finished"}>
                Score an invoice
              </Button>
            )}
            <a href={api.auditUrl(batchId)} download
              className="inline-flex items-center rounded-lg border border-line bg-raised px-3.5 py-2 text-sm
                font-medium hover:bg-wash">
              Export audit trail
            </a>
          </div>
        </div>
      </div>

      <nav className="flex gap-1 border-b border-line" aria-label="Batch views">
        {([["queue", "Review queue", b.pending_review], ["dashboard", "Dashboard", null]] as const).map(([key, label, n]) => (
          <a key={key} href={key === "queue" ? href("batches", batchId) : href("batches", batchId, "dashboard")}
            aria-current={tab === key ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === key
              ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}>
            {label}
            {n !== null && n > 0 && <span className="tabular ml-1.5 rounded-full bg-wash px-1.5 text-xs">{n}</span>}
          </a>
        ))}
      </nav>

      {tab === "queue" ? <Queue batchId={batchId} refreshKey={b.processed + b.pending_review} />
        : <DashboardView batchId={batchId} refreshKey={b.processed} />}
      {scoring && <ScoreDrawer batchId={batchId} onClose={() => setScoring(false)} />}
    </div>
  );
}

// ------------------------------------------------------------------------ review queue (US-02)

type Preset = "needs_review" | "all" | "auto_approve" | "auto_reject";

const PRESETS: { value: Preset; label: string; filters: ResultFilters }[] = [
  { value: "needs_review", label: "Needs review", filters: { action: "escalate", reviewed: false, sort: "confidence" } },
  { value: "all", label: "All", filters: {} },
  { value: "auto_approve", label: "Auto-approved", filters: { action: "auto_approve" } },
  { value: "auto_reject", label: "Auto-rejected", filters: { action: "auto_reject" } },
];

const PAGE = 50;

function Queue({ batchId, refreshKey }: { batchId: string; refreshKey: number }) {
  const [preset, setPreset] = useState<Preset>("needs_review");
  const [code, setCode] = useState<Code | "">("");
  const [band, setBand] = useState<Band | "">("");
  const [page, setPage] = useState(0);
  const filters: ResultFilters = {
    ...PRESETS.find((p) => p.value === preset)!.filters,
    code: code || undefined, band: band || undefined, limit: PAGE + 1, offset: page * PAGE,
  };
  const rows = useAsync(() => api.results(batchId, filters), [batchId, preset, code, band, page, refreshKey]);
  const shown = rows.data?.slice(0, PAGE) ?? [];
  const reset = () => setPage(0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Segmented label="Queue" value={preset} options={PRESETS} onChange={(v) => { setPreset(v); reset(); }} />
        <select aria-label="Exception type" className={inputBase} value={code}
          onChange={(e) => { setCode(e.target.value as Code | ""); reset(); }}>
          <option value="">All exception types</option>
          {(Object.keys(CODE_LABELS) as Code[]).map((c) => <option key={c} value={c}>{c === "clean" ? "OK" : c} · {CODE_LABELS[c]}</option>)}
        </select>
        <select aria-label="Confidence" className={inputBase} value={band}
          onChange={(e) => { setBand(e.target.value as Band | ""); reset(); }}>
          <option value="">Any confidence</option>
          {(["red", "amber", "green"] as Band[]).map((x) => <option key={x} value={x}>{BAND_LABELS[x]} confidence</option>)}
        </select>
        {preset === "needs_review" && <span className="pb-2 text-xs text-muted">Least confident first</span>}
      </div>

      {rows.error && <ErrorNote message={rows.error} />}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="text-left text-xs text-muted">
            <tr className="border-b border-line">
              <th className="px-4 py-2.5 font-medium">Invoice</th>
              <th className="px-3 py-2.5 font-medium">Supplier</th>
              <th className="px-3 py-2.5 text-right font-medium">Total</th>
              <th className="px-3 py-2.5 font-medium">Type</th>
              <th className="px-3 py-2.5 font-medium">Agent</th>
              <th className="px-3 py-2.5 font-medium">Confidence</th>
              <th className="px-4 py-2.5 font-medium">Finding</th>
            </tr>
          </thead>
          <tbody>
            {rows.loading && !rows.data ? (
              <tr><td colSpan={7}><Loading /></td></tr>
            ) : shown.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-muted">
                {preset === "needs_review" ? "Nothing waiting for review." : "No invoices match these filters."}
              </td></tr>
            ) : shown.map((r) => (
              <tr key={r.doc_id} className="cursor-pointer border-b border-line align-top last:border-0 hover:bg-wash"
                onClick={() => { window.location.hash = href("batches", batchId, "invoices", r.doc_id); }}>
                <td className="px-4 py-3">
                  <a href={href("batches", batchId, "invoices", r.doc_id)} className="font-medium hover:underline"
                    onClick={(e) => e.stopPropagation()}>{r.invoice_number ?? r.doc_id}</a>
                  <div className="whitespace-nowrap text-xs text-muted">{r.doc_id}{r.po_number ? ` · ${r.po_number}` : ""}</div>
                </td>
                <td className="max-w-48 truncate px-3 py-3" title={r.supplier_name ?? ""}>{r.supplier_name ?? "—"}</td>
                <td className="tabular px-3 py-3 text-right">{gbp(r.total_amount)}</td>
                <td className="px-3 py-3"><CodeBadge code={r.code} /></td>
                <td className="px-3 py-3">
                  <ActionBadge action={r.action} />
                  {r.review && (
                    <div className="mt-1 text-xs text-ink-2">
                      Analyst: {DECISION_LABELS[r.review]}{r.is_override ? " (override)" : ""}
                    </div>
                  )}
                </td>
                <td className="px-3 py-3"><ConfidenceBadge confidence={r.confidence} band={r.band} /></td>
                <td className="max-w-md px-4 py-3 text-ink-2"><span className="line-clamp-2">{stripPrefix(r.summary)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(page > 0 || (rows.data?.length ?? 0) > PAGE) && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <span className="text-muted">Page {page + 1}</span>
          <Button variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
          <Button variant="secondary" disabled={(rows.data?.length ?? 0) <= PAGE} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}

/** Briefs open with "Invoice X from Y: "; the queue already shows both, so lead with the finding. */
function stripPrefix(summary: string): string {
  return summary.replace(/^Invoice .+? from .+?: /, "");
}

// ------------------------------------------------------------------------ dashboard (US-04)

const ACTION_COLORS: Record<Action, string> = {
  auto_approve: "var(--color-series-1)",
  auto_reject: "var(--color-series-2)",
  escalate: "var(--color-series-3)",
};
const BAND_COLORS: Record<Band, { color: string; icon: string }> = {
  green: { color: "var(--color-good)", icon: "●" },
  amber: { color: "var(--color-warning)", icon: "▲" },
  red: { color: "var(--color-critical)", icon: "■" },
};

function DashboardView({ batchId, refreshKey }: { batchId: string; refreshKey: number }) {
  const { data: d, error } = useAsync(() => api.dashboard(batchId), [batchId, refreshKey]);
  if (error) return <ErrorNote message={error} />;
  if (!d) return <Loading />;
  if (d.invoices === 0) return <p className="py-10 text-center text-sm text-muted">No invoices processed yet.</p>;

  const exceptionRows = (Object.keys(CODE_LABELS) as Code[]).filter((c) => c !== "clean")
    .map((c) => ({ key: c, label: CODE_LABELS[c], value: d.by_code[c] ?? 0 }));
  const unclassified = d.by_code.unclassified ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Invoices processed" value={d.invoices.toLocaleString()}
          sub={`${d.exceptions} exceptions (${pct(d.exceptions / d.invoices)})`} />
        <Stat label="Decided without a human" value={pct(d.straight_through_rate)}
          sub="auto-approved or auto-rejected" />
        <Stat label="Exceptions auto-resolved" value={pct(d.auto_resolution_rate)}
          sub={`${d.auto_resolved_exceptions} of ${d.exceptions}`}
          target={{ ok: d.auto_resolution_rate >= 0.4 && d.auto_resolution_rate <= 0.6, text: "Target 40–60%" }} />
        <Stat label="Waiting for review" value={d.pending_review} sub={`${d.reviewed} reviewed so far`} />
        <Stat label="Analyst overrides" value={pct(d.override_rate, 1)}
          sub={`${d.overrides} changed · ${d.reversed_autonomous_decisions} auto-decisions reversed`}
          target={{ ok: d.override_rate < 0.15, text: "Target under 15%" }} />
        <Stat label="AI cost per invoice" value={d.llm.cost_per_invoice_gbp ? gbp(d.llm.cost_per_invoice_gbp) : "£0.00"}
          sub={`${d.llm.calls.toLocaleString()} model calls${d.llm.failed_calls ? `, ${d.llm.failed_calls} used rules instead` : ""}`}
          target={{ ok: d.llm.cost_per_invoice_gbp < 0.15, text: "Target under £0.15" }} />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Exceptions by type" className="lg:col-span-3">
          <BarChart rows={exceptionRows} total={d.exceptions} />
          {unclassified > 0 && (
            <p className="mt-3 text-sm text-ink-2">
              {unclassified} invoice{unclassified === 1 ? "" : "s"} could not be read reliably and went to manual entry.
            </p>
          )}
        </Card>
        <div className="space-y-6 lg:col-span-2">
          <Card title="What the agent did">
            <StackedBar label="Agent actions" segments={(Object.keys(ACTION_LABELS) as Action[]).map((a) => ({
              key: a, label: ACTION_LABELS[a], value: d.by_action[a] ?? 0, color: ACTION_COLORS[a],
            }))} />
          </Card>
          <Card title="How confident it was">
            <StackedBar label="Confidence bands" segments={(["green", "amber", "red"] as Band[]).map((b) => ({
              key: b, label: BAND_LABELS[b], value: d.by_band[b] ?? 0, color: BAND_COLORS[b].color,
              icon: BAND_COLORS[b].icon,
            }))} />
          </Card>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Suppliers with the most exceptions" className="lg:col-span-3">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr><th className="pb-2 font-medium">Supplier</th><th className="pb-2 pl-3 text-right font-medium">Invoices</th>
                <th className="pb-2 pl-3 text-right font-medium">Exceptions</th><th className="hidden pb-2 pl-4 font-medium sm:table-cell">Types</th></tr>
            </thead>
            <tbody>
              {d.top_suppliers.map((s) => (
                <tr key={s.supplier} className="border-t border-line">
                  <td className="py-2">{s.supplier}</td>
                  <td className="tabular py-2 text-right text-ink-2">{s.invoices}</td>
                  <td className="tabular py-2 text-right font-medium">{s.exceptions}
                    <span className="ml-1 text-xs font-normal text-muted">({pct(s.exceptions / s.invoices)})</span></td>
                  <td className="hidden py-2 pl-4 sm:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(s.codes).map(([c, n]) => (
                        <span key={c} className="text-xs text-ink-2" title={CODE_LABELS[c as Code]}>
                          <span className="font-mono">{c}</span>×{n}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Why analysts overrode the agent" className="lg:col-span-2">
          {Object.keys(d.override_reasons).length === 0 ? (
            <p className="text-sm text-muted">No overrides yet. Reasons appear here as analysts correct the agent, showing
              where it needs to improve.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {Object.entries(d.override_reasons).sort((a, b) => b[1] - a[1]).map(([r, n]) => (
                <li key={r} className="flex justify-between gap-3">
                  <span className="text-ink-2">{REASON_LABELS[r as keyof typeof REASON_LABELS] ?? r}</span>
                  <span className="tabular font-medium">{n}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-5 border-t border-line pt-4 text-sm">
            <div className="mb-2 font-medium">Audit trail (US-05)</div>
            <div className="flex flex-wrap gap-2">
              <a className="text-accent hover:underline" href={api.auditUrl(batchId)} download>All decisions (CSV)</a>
              <span className="text-muted">·</span>
              <a className="text-accent hover:underline" href={api.auditUrl(batchId, "auto_approve")} download>
                Auto-approved only</a>
            </div>
          </div>
        </Card>
      </div>
      <p className="text-xs text-muted">Median processing time {d.median_latency_ms} ms per invoice.</p>
    </div>
  );
}

// ------------------------------------------------------------------------ single invoice scoring (P0)

function ScoreDrawer({ batchId, onClose }: { batchId: string; onClose: () => void }) {
  const [kind, setKind] = useState<"file" | "text" | "json">("file");
  const [file, setFile] = useState<File>();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const res = kind === "file" ? await api.uploadDocument(batchId, file!)
        : kind === "text" ? await api.scoreInvoice(batchId, { document: text })
          : await api.scoreInvoice(batchId, { invoice: JSON.parse(text) });
      window.location.hash = href("batches", batchId, "invoices", res.result.doc_id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Drawer title="Score an invoice" onClose={onClose}>
      <p className="mb-5 text-sm text-ink-2">
        The invoice is matched against this batch's purchase orders and goods receipts, and checked for duplicates
        against every invoice already in the batch.
      </p>
      <div className="space-y-4">
        <Segmented label="Invoice as" value={kind} onChange={setKind} options={[
          { value: "file", label: "Upload document" }, { value: "text", label: "Paste text" },
          { value: "json", label: "Paste JSON" }]} />
        {kind === "file" ? (
          <Field label="Invoice document" hint="PDF or text, up to 10 MB. Needs an AI model (live or demo mode).">
            <input type="file" accept=".pdf,.txt,application/pdf,text/plain" className="text-sm"
              onChange={(e) => setFile(e.target.files?.[0])} />
          </Field>
        ) : (
          <Field label={kind === "text" ? "Invoice text" : "Invoice JSON"}
            hint={kind === "json" ? "Fields as in data/synthetic/invoices.json." : "Needs an AI model (live or demo mode)."}>
            <textarea className={`${inputClass} h-72 font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
        )}
        {error && <ErrorNote message={error} />}
        <Button disabled={busy || (kind === "file" ? !file : !text.trim())} onClick={submit}>
          {busy ? "Scoring…" : "Score invoice"}
        </Button>
      </div>
    </Drawer>
  );
}
