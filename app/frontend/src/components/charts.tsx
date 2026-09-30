import { useState, type ReactNode } from "react";

import { pct } from "../format";

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

function useTooltip() {
  const [tip, setTip] = useState<Tip | null>(null);
  const bind = (content: ReactNode) => ({
    onMouseMove: (e: React.MouseEvent<HTMLElement>) => {
      const box = (e.currentTarget.closest("[data-chart]") as HTMLElement).getBoundingClientRect();
      setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content });
    },
    onMouseLeave: () => setTip(null),
  });
  const node = tip && (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border
        border-line bg-raised px-2.5 py-1.5 text-xs shadow-lg"
      style={{ left: tip.x, top: tip.y - 10 }}
    >
      {tip.content}
    </div>
  );
  return { bind, node };
}

/** Horizontal bars for one series (magnitude by category). Single hue; values labelled at the bar end. */
export function BarChart({ rows, color = "var(--color-series-1)", total }: {
  rows: { key: string; label: string; value: number }[];
  color?: string;
  total?: number;
}) {
  const { bind, node } = useTooltip();
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div data-chart className="relative">
      <ul className="space-y-2 text-sm" aria-label="Values by category">
        {rows.map((r) => (
          <li key={r.key}
            {...bind(<><div className="font-medium">{r.label}</div><div className="tabular text-ink-2">
              {r.value}{total ? ` · ${pct(r.value / total, 1)} of total` : ""}</div></>)}
            className="grid grid-cols-1 items-center gap-x-3 gap-y-0.5 sm:grid-cols-[15rem_1fr]">
            <span className="truncate">
              <span className="font-mono text-xs text-muted">{r.key}</span>{" "}
              <span className="text-ink-2">{r.label}</span>
            </span>
            <span className="flex h-5 items-center gap-2 border-l border-baseline">
              <span className="block h-3.5 rounded-r-[4px] transition-[width]"
                style={{ width: `${(r.value / max) * 85}%`, minWidth: r.value ? 2 : 0, background: color }} />
              <span className="tabular text-xs text-ink-2">{r.value}</span>
            </span>
          </li>
        ))}
      </ul>
      {node}
    </div>
  );
}

export interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
  icon?: string;
}

/** Part-to-whole in one bar. 2px surface gaps between segments; legend doubles as direct labels. */
export function StackedBar({ segments, label }: { segments: Segment[]; label: string }) {
  const { bind, node } = useTooltip();
  const total = segments.reduce((s, x) => s + x.value, 0);
  const shown = segments.filter((s) => s.value > 0);
  return (
    <div data-chart className="relative">
      <div className="flex h-4 w-full gap-[2px]" role="img" aria-label={`${label}: ${shown.map((s) =>
        `${s.label} ${s.value}`).join(", ")}`}>
        {shown.map((s, i) => (
          <div
            key={s.key}
            {...bind(<><div className="font-medium">{s.label}</div>
              <div className="tabular text-ink-2">{s.value} · {pct(s.value / total, 1)}</div></>)}
            className={`h-full ${i === 0 ? "rounded-l-[4px]" : ""} ${i === shown.length - 1 ? "rounded-r-[4px]" : ""}`}
            style={{ flexGrow: s.value, flexBasis: 0, background: s.color, minWidth: 2 }}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
        {segments.map((s) => (
          <li key={s.key} className="flex items-center gap-2">
            <span aria-hidden className="inline-flex size-3 items-center justify-center rounded-sm text-[8px] text-white"
              style={{ background: s.color }}>{s.icon}</span>
            <span className="text-ink-2">{s.label}</span>
            <span className="tabular font-medium">{s.value}</span>
            <span className="tabular text-muted">{total ? pct(s.value / total) : "0%"}</span>
          </li>
        ))}
      </ul>
      {node}
    </div>
  );
}

/** Stat tile. Optional target renders as a status line with icon + text, never colour alone. */
export function Stat({ label, value, sub, target }: {
  label: string; value: ReactNode; sub?: ReactNode; target?: { ok: boolean; text: string };
}) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3.5">
      <div className="text-xs font-medium text-ink-2">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
      {target && (
        <div className={`mt-1.5 flex items-center gap-1 text-xs font-medium ${target.ok ? "text-good-ink"
          : "text-critical-ink"}`}>
          <span aria-hidden>{target.ok ? "✓" : "!"}</span>
          {target.text}
        </div>
      )}
    </div>
  );
}
