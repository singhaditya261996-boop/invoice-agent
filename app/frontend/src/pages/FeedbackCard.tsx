import { api, type CategoryEvidence } from "../api";
import { Card, ErrorNote, Loading } from "../components/ui";
import { CODE_LABELS, pct, REASON_LABELS } from "../format";
import { useAsync } from "../hooks";

const BADGE: Record<CategoryEvidence["recommendation"], { label: string; className: string }> = {
  widen: { label: "Could run alone", className: "bg-good/15 text-good-ink" },
  narrow: { label: "Pull back", className: "bg-critical/15 text-critical-ink" },
  hold: { label: "Hold", className: "bg-wash text-ink-2" },
  insufficient_evidence: { label: "Not enough reviews", className: "bg-wash text-muted" },
};

/** D-01's loop, closed: what analyst overrides say about where the boundary should sit (D-16). */
export function FeedbackCard({ batchId }: { batchId: string }) {
  const { data, error } = useAsync(() => api.feedback(batchId), [batchId]);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Card title="Where autonomy should move next"><Loading /></Card>;

  const seen = data.categories.filter((c) => c.reviewed > 0);
  return (
    <Card title="Where autonomy should move next">
      {data.actionable.length > 0 ? (
        <ul className="mb-5 space-y-3">
          {data.actionable.map((note, i) => {
            const [headline, ...rest] = note.split(" — ");
            return (
              <li key={i} className="rounded-lg border border-line bg-raised px-4 py-3 text-sm">
                <div className="font-medium">{headline}</div>
                <p className="mt-1 text-ink-2">{rest.join(" — ")}</p>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mb-5 text-sm text-ink-2">
          Nothing to change yet. Recommendations appear once a category has {data.min_reviews_required}{" "}
          reviews and a settled override rate.
        </p>
      )}

      <div className="-mx-5 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="text-left text-xs text-muted">
            <tr className="border-y border-line">
              <th className="px-5 py-2 font-medium">Exception</th>
              <th className="px-3 py-2 text-right font-medium">Reviews</th>
              <th className="px-3 py-2 text-right font-medium">Overridden</th>
              <th className="px-3 py-2 text-right font-medium">Reversed</th>
              <th className="px-3 py-2 font-medium">Today</th>
              <th className="px-5 py-2 font-medium">Evidence says</th>
            </tr>
          </thead>
          <tbody>
            {seen.map((c) => {
              const badge = BADGE[c.recommendation];
              return (
                <tr key={c.code} className="border-b border-line last:border-0 align-top">
                  <td className="px-5 py-2.5">
                    <span className="font-mono text-xs text-muted">{c.code === "clean" ? "OK" : c.code}</span>{" "}
                    {CODE_LABELS[c.code]}
                    {!c.eligible && <div className="text-xs text-muted">never resolved automatically</div>}
                    {c.top_override_reason && (
                      <div className="text-xs text-muted">mostly: {REASON_LABELS[c.top_override_reason]}</div>
                    )}
                  </td>
                  <td className="tabular px-3 py-2.5 text-right">{c.reviewed}</td>
                  <td className="tabular px-3 py-2.5 text-right">
                    {c.override_rate === null ? "—" : pct(c.override_rate)}
                    {c.override_rate_upper !== null && (
                      <div className="text-xs text-muted">≤ {pct(c.override_rate_upper)}</div>
                    )}
                  </td>
                  <td className="tabular px-3 py-2.5 text-right">{c.reversals || "—"}</td>
                  <td className="px-3 py-2.5 text-ink-2">{c.autonomous_today ? "Agent" : "Analyst"}</td>
                  <td className="px-5 py-2.5">
                    <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${badge.className}`}>
                      {badge.label}
                    </span>
                    <p className="mt-1 max-w-sm text-xs text-ink-2">{c.reason}</p>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
        {data.note ? `${data.note} ` : ""}
        The agent never widens its own authority: these are recommendations for a manager to apply, and the
        policy sandbox shows what each one would do to this batch. "≤" is the upper bound of the override
        rate given the sample size.
      </p>
    </Card>
  );
}
