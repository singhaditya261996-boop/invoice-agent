import { useState } from "react";

import { api, type PolicyChange } from "../api";
import { Stat } from "../components/charts";
import { ActionBadge, Card, CodeBadge, ErrorNote, Field, Loading, Segmented } from "../components/ui";
import { gbp, pct } from "../format";
import { useAsync } from "../hooks";
import { APPROVAL_CONFIDENCES, AUTONOMY_SETS, BASELINE, TOLERANCES, type PolicyIndices } from "../policy";

/** US-04 / D-01 / D-02: make the autonomy trade-off something a manager can inspect, not argue about. */
export function PolicyPanel({ batchId }: { batchId: string }) {
  const [indices, setIndices] = useState<PolicyIndices>(BASELINE);
  const { data: sim, error, loading } = useAsync(() => api.simulate(batchId, indices),
    [batchId, indices.tolerance, indices.confidence, indices.autonomy]);
  const set = (key: keyof PolicyIndices) => (value: string) =>
    setIndices({ ...indices, [key]: Number(value) });
  const atBaseline = JSON.stringify(indices) === JSON.stringify(BASELINE);

  return (
    <div className="space-y-6">
      <Card title="What if the rules were different?">
        <p className="mb-5 max-w-3xl text-sm text-ink-2">
          The agent settles only what it is allowed to settle. Loosen the rules and it handles more
          without a human — on weaker evidence. This re-runs the whole batch under the thresholds you
          pick and shows exactly which invoices change hands, so the trade-off is measurable rather
          than a matter of opinion.
        </p>
        <div className="grid gap-5 lg:grid-cols-3">
          <Field label="Amount tolerance" hint={TOLERANCES[indices.tolerance].detail}>
            <Segmented label="Amount tolerance" value={String(indices.tolerance)} onChange={set("tolerance")}
              options={TOLERANCES.map((t, i) => ({ value: String(i), label: t.label }))} />
          </Field>
          <Field label="Approve only above" hint="How sure the agent must be to pay without a human">
            <Segmented label="Approve only above" value={String(indices.confidence)} onChange={set("confidence")}
              options={APPROVAL_CONFIDENCES.map((c, i) => ({ value: String(i), label: c.label }))} />
          </Field>
          <Field label="May resolve alone" hint={AUTONOMY_SETS[indices.autonomy].detail}>
            <Segmented label="May resolve alone" value={String(indices.autonomy)} onChange={set("autonomy")}
              options={AUTONOMY_SETS.map((a, i) => ({ value: String(i), label: a.label }))} />
          </Field>
        </div>
      </Card>

      {error && <ErrorNote message={error} />}
      {!sim ? <Loading label="Re-running the batch…" /> : (
        <div className={`space-y-6 transition-opacity ${loading ? "opacity-50" : ""}`}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Exceptions settled without a human"
              value={<Delta before={sim.before.auto_resolution_rate} after={sim.after.auto_resolution_rate} />}
              sub={atBaseline ? "today's rules" : `was ${pct(sim.before.auto_resolution_rate)}`}
              target={{ ok: sim.after.auto_resolution_rate >= 0.4 && sim.after.auto_resolution_rate <= 0.6,
                text: "Target 40–60%" }} />
            <Stat label="All invoices decided without a human"
              value={<Delta before={sim.before.straight_through_rate} after={sim.after.straight_through_rate} />}
              sub={atBaseline ? "today's rules" : `was ${pct(sim.before.straight_through_rate)}`} />
            <Stat label="Would no longer reach an analyst" value={sim.newly_autonomous}
              sub="the agent would settle these alone" />
            <Stat label="Would go back to an analyst" value={sim.newly_escalated}
              sub="the agent settles these today" />
          </div>

          <Card title={sim.risk.length && !atBaseline ? "What you would be accepting" : "Effect on this batch"}>
            <ul className="space-y-2 text-sm">
              {sim.risk.map((note, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className={atBaseline ? "text-muted" : "text-critical-ink"}>
                    {atBaseline ? "ⓘ" : "!"}
                  </span>
                  {note}
                </li>
              ))}
            </ul>
            <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
              Rules in force: {Object.values(sim.applied).join(" · ")}. Re-run with
              {sim.llm === "replayed" ? " recorded model responses" : " rule-based fallbacks"}, so exploring
              costs nothing.
            </p>
          </Card>

          {sim.changed.length > 0 && (
            <Card title={`Invoices that change hands (${sim.changed.length})`}>
              <div className="-mx-5 overflow-x-auto">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="px-5 py-2 font-medium">Invoice</th>
                      <th className="px-3 py-2 text-right font-medium">Total</th>
                      <th className="px-3 py-2 font-medium">Today</th>
                      <th className="px-3 py-2 font-medium">Under these rules</th>
                      <th className="px-5 py-2 text-right font-medium">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sim.changed.map((c) => <ChangeRow key={c.doc_id} change={c} />)}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

function Delta({ before, after }: { before: number; after: number }) {
  if (before === after) return <>{pct(after)}</>;
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-muted line-through decoration-1">{pct(before)}</span>
      <span aria-hidden className="text-muted">→</span>
      {pct(after)}
    </span>
  );
}

function ChangeRow({ change: c }: { change: PolicyChange }) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="px-5 py-2.5">
        <div className="font-medium">{c.invoice_number ?? c.doc_id}</div>
        <div className="text-xs text-muted">{c.supplier_name ?? c.doc_id}</div>
      </td>
      <td className="tabular px-3 py-2.5 text-right">{gbp(c.total_amount)}</td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-2"><CodeBadge code={c.before_code} />
          <ActionBadge action={c.before_action} /></div>
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-2"><CodeBadge code={c.after_code} />
          <ActionBadge action={c.after_action} /></div>
      </td>
      <td className="tabular px-5 py-2.5 text-right">{pct(c.after_confidence)}</td>
    </tr>
  );
}
