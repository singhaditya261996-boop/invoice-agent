// Typed client for the FastAPI backend (app/api). Decimal amounts arrive as strings.

const BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

/** The hosted build has no backend: it reads a frozen batch from public/demo instead. */
export const STATIC_DEMO = import.meta.env.VITE_DEMO_DATA === "1";

export type Mode = "demo" | "live" | "offline";
export type Code = "clean" | "E01" | "E02" | "E03" | "E04" | "E05" | "E06" | "E07" | "E08";
export type Action = "auto_approve" | "auto_reject" | "escalate";
export type Band = "green" | "amber" | "red";
export type Decision = "approve" | "reject" | "hold";
export type OverrideReason =
  | "agent_misidentified_po"
  | "amount_difference_is_contractual_adjustment"
  | "not_actually_a_duplicate"
  | "wrong_exception_category"
  | "partial_delivery_confirmed_offline"
  | "supplier_name_variant_acceptable"
  | "extraction_error"
  | "other";

export interface BatchSummary {
  id: string;
  name: string;
  mode: Mode;
  status: "queued" | "processing" | "complete";
  created_at: string;
  total: number;
  processed: number;
  failed: number;
  escalated: number;
  pending_review: number;
}

export interface ResultRow {
  doc_id: string;
  invoice_number: string | null;
  supplier_name: string | null;
  total_amount: string | null;
  po_number: string | null;
  match_method: string | null;
  code: Code | null;
  action: Action;
  confidence: number;
  band: Band;
  summary: string;
  review: Decision | null;
  is_override: boolean;
}

export interface LineItem {
  description: string;
  quantity: string;
  unit_price: string;
  tax?: string;
  total: string;
}

export interface Invoice {
  invoice_number: string;
  supplier_name: string;
  po_reference: string | null;
  invoice_date: string;
  due_date: string;
  line_items: LineItem[];
  subtotal: string;
  tax_amount: string;
  total_amount: string;
  currency: string;
}

export interface PurchaseOrder {
  po_number: string;
  supplier_name: string;
  supplier_id: string;
  order_date: string;
  delivery_date: string;
  line_items: LineItem[];
  total_amount: string;
  cost_centre: string;
  approver: string;
  payment_terms: string;
  status: string;
}

export interface GoodsReceipt {
  gr_number: string;
  po_number: string;
  receipt_date: string;
  line_items: { description: string; quantity_received: string }[];
  receiver: string;
  notes: string;
}

export interface Discrepancy {
  check: string;
  field: string;
  invoice_value: string | null;
  reference_value: string | null;
  detail: string;
  suggested_code: Code;
  confidence: number;
}

export interface Brief {
  summary: string;
  what_i_found: string[];
  what_i_checked: string[];
  what_i_could_not_resolve: string;
  recommended_action: string;
  evidence: string[];
}

export interface InvoiceResult {
  doc_id: string;
  invoice_number: string | null;
  processed_at: string;
  mode: Mode;
  extraction: {
    invoice: Invoice | null;
    confidence: number;
    missing_fields: string[];
    issues: string[];
    method: string;
    needs_manual_entry: boolean;
  };
  match: {
    matched_po: PurchaseOrder | null;
    method: string;
    score: number;
    candidates: { po_number: string; score: number; reasons: string[] }[];
  } | null;
  validation: { discrepancies: Discrepancy[]; checks_performed: string[]; goods_receipt: GoodsReceipt | null } | null;
  classification: {
    code: Code | null;
    confidence: number;
    raw_confidence: number | null;
    band: Band;
    action: Action;
    rationale: string;
    used_llm: boolean;
  };
  brief: Brief | null;
  llm_calls: { step: string; model: string; input_tokens: number; output_tokens: number; cached: boolean;
    latency_ms: number; error: string | null }[];
  latency_ms: number;
}

export interface Review {
  doc_id: string;
  original_code: Code | null;
  original_action: Action;
  new_code: Code | null;
  decision: Decision;
  is_override: boolean;
  reason: OverrideReason | null;
  note: string | null;
  analyst: string;
  created_at: string;
}

export interface ResultDetail {
  result: InvoiceResult;
  review: Review | null;
}

export interface Dashboard {
  invoices: number;
  by_code: Record<string, number>;
  by_action: Record<string, number>;
  by_band: Record<string, number>;
  exceptions: number;
  auto_resolved_exceptions: number;
  auto_resolution_rate: number;
  straight_through_rate: number;
  pending_review: number;
  reviewed: number;
  overrides: number;
  override_rate: number;
  reversed_autonomous_decisions: number;
  override_reasons: Record<string, number>;
  top_suppliers: { supplier: string; invoices: number; exceptions: number; codes: Record<string, number> }[];
  median_latency_ms: number;
  llm: { calls: number; cached_calls: number; failed_calls: number; input_tokens: number; output_tokens: number;
    cost_usd: number; cost_gbp: number; cost_per_invoice_gbp: number };
}

export interface AgentConfig {
  default_mode: Mode;
  llm_model: string;
  tolerance: { pct: string; absolute_gbp: string; rule: string };
  auto_approve_confidence: number;
  auto_reject_duplicate_confidence: number;
  auto_resolvable: Code[];
  min_match_score: number;
  confidence_bands: Record<Band, string>;
  vat_rate: string;
  duplicate_window_days: number;
}

export interface PolicyOutcome {
  by_action: Record<string, number>;
  auto_resolution_rate: number;
  straight_through_rate: number;
}

export interface PolicyChange {
  doc_id: string;
  invoice_number: string | null;
  supplier_name: string | null;
  total_amount: string | null;
  before_code: Code | null;
  before_action: Action;
  after_code: Code | null;
  after_action: Action;
  after_confidence: number;
}

export interface PolicySimulation {
  applied: Record<string, string>;
  llm: string;
  before: PolicyOutcome;
  after: PolicyOutcome;
  changed: PolicyChange[];
  newly_autonomous: number;
  newly_escalated: number;
  risk: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

import { scenarioBody, type PolicyIndices } from "./policy";
import { staticApi } from "./staticApi";

export interface ResultFilters {
  code?: Code;
  action?: Action;
  band?: Band;
  reviewed?: boolean;
  sort?: "order" | "confidence";
  limit?: number;
  offset?: number;
}

const liveApi = {
  config: () => request<AgentConfig>("/config"),
  batches: () => request<BatchSummary[]>("/batches"),
  batch: (id: string) => request<BatchSummary>(`/batches/${id}`),
  createDemo: (body: { mode: Mode; input: "structured" | "documents"; limit?: number }) =>
    request<BatchSummary>("/batches/demo", json(body)),
  createBatch: (body: unknown) => request<BatchSummary>("/batches", json(body)),
  results: (id: string, f: ResultFilters) => {
    const q = new URLSearchParams();
    Object.entries(f).forEach(([k, v]) => v !== undefined && q.set(k, String(v)));
    return request<ResultRow[]>(`/batches/${id}/results?${q}`);
  },
  result: (id: string, doc: string) => request<ResultDetail>(`/batches/${id}/results/${doc}`),
  review: (id: string, doc: string, body: { decision: Decision; new_code?: Code | null; reason?: OverrideReason | null;
    note?: string; analyst: string }) => request<Review>(`/batches/${id}/results/${doc}/review`, json(body)),
  dashboard: (id: string) => request<Dashboard>(`/batches/${id}/dashboard`),
  purchaseOrder: (id: string, po: string) => request<PurchaseOrder>(`/batches/${id}/purchase-orders/${po}`),
  goodsReceipt: (id: string, po: string) =>
    request<GoodsReceipt>(`/batches/${id}/purchase-orders/${po}/goods-receipt`),
  source: async (id: string, doc: string): Promise<{ type: string; text: string }> => {
    const res = await fetch(`${BASE}/batches/${id}/sources/${doc}`);
    if (!res.ok) throw new ApiError(res.status, "source not found");
    return { type: res.headers.get("content-type") ?? "", text: await res.text() };
  },
  scoreInvoice: (id: string, body: { invoice?: unknown; document?: string }) =>
    request<ResultDetail>(`/batches/${id}/invoices`, json(body)),
  uploadDocument: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ResultDetail>(`/batches/${id}/documents`, { method: "POST", body: form });
  },
  simulate: (id: string, indices: PolicyIndices) =>
    request<PolicySimulation>(`/batches/${id}/simulate`, json(scenarioBody(indices))),
  auditUrl: (id: string, action?: Action) =>
    `${BASE}/batches/${id}/audit?format=csv${action ? `&action=${action}` : ""}`,
};

// Chosen at build time. staticApi imports only types from this module, so there is no runtime cycle.
export const api = (STATIC_DEMO ? staticApi : liveApi) as typeof liveApi;
