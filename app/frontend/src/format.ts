import type { Action, Band, Code, Decision, Mode, OverrideReason } from "./api";

export const CODE_LABELS: Record<Code, string> = {
  clean: "Clean match",
  E01: "Amount within tolerance",
  E02: "Amount over tolerance",
  E03: "Quantity variance",
  E04: "Duplicate invoice",
  E05: "Missing PO reference",
  E06: "PO already closed",
  E07: "Tax calculation error",
  E08: "Supplier name mismatch",
};

export const ACTION_LABELS: Record<Action, string> = {
  auto_approve: "Auto-approved",
  auto_reject: "Auto-rejected",
  escalate: "Escalated",
};

export const DECISION_LABELS: Record<Decision, string> = { approve: "Approve", reject: "Reject", hold: "Hold" };

export const BAND_LABELS: Record<Band, string> = { green: "High", amber: "Medium", red: "Low" };

export const MODE_LABELS: Record<Mode, { label: string; help: string }> = {
  demo: { label: "Demo", help: "Cached model responses. No API cost, deterministic." },
  live: { label: "Live", help: "Real Claude API calls. Needs an API key on the server; costs money." },
  offline: { label: "Rules only", help: "No model. Rule-based fallbacks for every AI step." },
};

export const REASON_LABELS: Record<OverrideReason, string> = {
  agent_misidentified_po: "Agent matched the wrong PO",
  amount_difference_is_contractual_adjustment: "Amount difference is a contractual adjustment",
  not_actually_a_duplicate: "Not actually a duplicate",
  wrong_exception_category: "Wrong exception category",
  partial_delivery_confirmed_offline: "Partial delivery confirmed offline",
  supplier_name_variant_acceptable: "Supplier name variant is acceptable",
  extraction_error: "Invoice was read incorrectly",
  other: "Other (explain in note)",
};

const gbpFormat = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

export function gbp(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return gbpFormat.format(Number(value));
}

export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function date(value: string): string {
  return new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function codeLabel(code: Code | null): string {
  return code ? CODE_LABELS[code] : "Not classified";
}
