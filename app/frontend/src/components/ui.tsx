import { useEffect, type ReactNode } from "react";

import type { Action, Band, Code } from "../api";
import { ACTION_LABELS, BAND_LABELS, codeLabel, pct } from "../format";

export function Card({ title, action, children, className = "" }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="text-sm font-semibold">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Button({ children, variant = "primary", className = "", ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const styles = {
    primary: "bg-accent text-accent-ink hover:opacity-90",
    secondary: "border border-line bg-raised text-ink hover:bg-wash",
    ghost: "text-ink-2 hover:bg-wash hover:text-ink",
  }[variant];
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition
        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed
        disabled:opacity-50 ${styles} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputBase =
  "rounded-lg border border-line bg-raised px-3 py-2 text-sm text-ink focus-visible:outline-2 " +
  "focus-visible:outline-accent";
export const inputClass = `w-full ${inputBase}`;

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-wash p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm transition ${value === o.value
            ? "bg-raised font-medium text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const BAND_STYLE: Record<Band, { color: string; icon: string }> = {
  green: { color: "bg-good", icon: "●" },
  amber: { color: "bg-warning", icon: "▲" },
  red: { color: "bg-critical", icon: "■" },
};

/** Trust design §7.1: colour-coded confidence, always with icon and label, never colour alone. */
export function ConfidenceBadge({ confidence, band, size = "sm" }: { confidence: number; band: Band; size?: "sm" | "lg" }) {
  const s = BAND_STYLE[band];
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-raised
        font-medium tabular ${size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs"}`}
      title={`${BAND_LABELS[band]} confidence`}
    >
      <span aria-hidden className={`inline-flex size-2.5 items-center justify-center rounded-full ${s.color}`} />
      {pct(confidence)}
      <span className="text-muted">{BAND_LABELS[band]}</span>
    </span>
  );
}

const ACTION_ICON: Record<Action, string> = { auto_approve: "✓", auto_reject: "✕", escalate: "⚑" };

export function ActionBadge({ action }: { action: Action }) {
  const tone = action === "escalate" ? "bg-accent-soft/60 text-ink" : "bg-wash text-ink-2";
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}>
      <span aria-hidden>{ACTION_ICON[action]}</span>
      {ACTION_LABELS[action]}
    </span>
  );
}

export function CodeBadge({ code, withLabel = false }: { code: Code | null; withLabel?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs" title={codeLabel(code)}>
      <span className="rounded border border-line bg-raised px-1.5 py-0.5 font-mono font-medium">
        {code === "clean" ? "OK" : code ?? "—"}
      </span>
      {withLabel && <span className="text-ink-2">{codeLabel(code)}</span>}
    </span>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-critical/40 bg-critical/10 px-4 py-3 text-sm">
      <span className="font-medium text-critical-ink">Something went wrong. </span>
      {message}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="py-10 text-center text-sm text-muted">{label}</p>;
}

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal aria-label={title}>
      <button aria-label="Close" className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-2xl flex-col bg-surface shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Close panel">✕</Button>
        </header>
        <div className="flex-1 overflow-auto p-5">{children}</div>
      </div>
    </div>
  );
}
