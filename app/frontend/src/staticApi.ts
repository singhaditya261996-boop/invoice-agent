// Backend-free implementation of the API client for the hosted demo (VITE_DEMO_DATA=1).
//
// The data in public/demo was produced by driving the real API through its own endpoints, so these
// responses match the live ones. What cannot be faked is persistence: reviews are kept in this
// browser only, and anything that would process a new invoice is unavailable without a server.

import type {
  Action, BatchSummary, Dashboard, Decision, GoodsReceipt, OverrideReason, PurchaseOrder, ResultDetail,
  ResultFilters, ResultRow, Review,
} from "./api";
import { ApiError } from "./api";

const BASE = `${import.meta.env.BASE_URL}demo/`;
const REVIEWS_KEY = "invoice-agent.demo-reviews";

async function file<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(res.status, `not found in the demo data: ${path}`);
  return res.json() as Promise<T>;
}

function storedReviews(): Record<string, Review> {
  try {
    return JSON.parse(localStorage.getItem(REVIEWS_KEY) ?? "{}") as Record<string, Review>;
  } catch {
    return {};
  }
}

function storeReview(review: Review): void {
  try {
    localStorage.setItem(REVIEWS_KEY, JSON.stringify({ ...storedReviews(), [review.doc_id]: review }));
  } catch {
    /* private browsing: the review still applies to this page view */
  }
}

const unavailable = (what: string) =>
  Promise.reject(new ApiError(501, `${what} needs the API. Run it locally with "make demo" — the hosted demo `
    + `replays a fixed batch.`));

export const staticApi = {
  config: () => file<unknown>("config.json") as Promise<never>,
  batches: () => file<BatchSummary[]>("batches.json"),
  batch: (_id: string) => file<BatchSummary>("batch.json"),

  results: async (_id: string, f: ResultFilters): Promise<ResultRow[]> => {
    const reviews = storedReviews();
    let rows = (await file<ResultRow[]>("results.json")).map((r) => {
      const review = reviews[r.doc_id];
      return review ? { ...r, review: review.decision, is_override: review.is_override } : r;
    });
    rows = rows.filter((r) =>
      (f.code === undefined || r.code === f.code)
      && (f.action === undefined || r.action === f.action)
      && (f.band === undefined || r.band === f.band)
      && (f.reviewed === undefined || (r.review !== null) === f.reviewed));
    if (f.sort === "confidence") rows.sort((a, b) => a.confidence - b.confidence);
    const offset = f.offset ?? 0;
    return rows.slice(offset, offset + (f.limit ?? 100));
  },

  result: async (_id: string, doc: string): Promise<ResultDetail> => {
    const detail = await file<ResultDetail>(`results/${doc}.json`);
    return { ...detail, review: storedReviews()[doc] ?? detail.review };
  },

  dashboard: async (_id: string): Promise<Dashboard> => {
    const dashboard = await file<Dashboard>("dashboard.json");
    const reviews = Object.values(storedReviews());
    if (reviews.length === 0) return dashboard;
    const overrides = reviews.filter((r) => r.is_override);
    const reversed = overrides.filter((r) =>
      (r.original_action === "auto_approve" && r.decision !== "approve")
      || (r.original_action === "auto_reject" && r.decision !== "reject"));
    const reasons: Record<string, number> = {};
    for (const r of overrides) if (r.reason) reasons[r.reason] = (reasons[r.reason] ?? 0) + 1;
    return {
      ...dashboard,
      reviewed: reviews.length,
      pending_review: Math.max(0, dashboard.pending_review
        - reviews.filter((r) => r.original_action === "escalate").length),
      overrides: overrides.length,
      override_rate: overrides.length / dashboard.invoices,
      reversed_autonomous_decisions: reversed.length,
      override_reasons: reasons,
    };
  },

  review: async (_id: string, doc: string, body: {
    decision: Decision; new_code?: string | null; reason?: OverrideReason | null; note?: string; analyst: string;
  }): Promise<Review> => {
    const { result } = await staticApi.result(_id, doc);
    const c = result.classification;
    const newCode = (body.new_code ?? c.code) as Review["new_code"];
    const isOverride = (c.code !== null && newCode !== c.code)
      || (c.action === "auto_approve" && body.decision !== "approve")
      || (c.action === "auto_reject" && body.decision !== "reject");
    if (isOverride && !body.reason) {
      throw new ApiError(422, "a reason code is required when overriding the agent (D-05)");
    }
    const review: Review = {
      doc_id: doc, original_code: c.code, original_action: c.action as Action, new_code: newCode,
      decision: body.decision, is_override: isOverride, reason: body.reason ?? null, note: body.note ?? null,
      analyst: body.analyst, created_at: new Date().toISOString(),
    };
    storeReview(review);
    return review;
  },

  purchaseOrder: (_id: string, po: string) => file<PurchaseOrder>(`purchase-orders/${po}.json`),
  goodsReceipt: (_id: string, po: string) => file<GoodsReceipt>(`goods-receipts/${po}.json`),
  source: async (_id: string, doc: string) => {
    const res = await fetch(`${BASE}sources/${doc}.txt`);
    if (!res.ok) throw new ApiError(res.status, "source not found");
    return { type: "text/plain", text: await res.text() };
  },
  auditUrl: (_id: string, _action?: Action) => `${BASE}audit.csv`,

  createDemo: () => unavailable("Starting a batch"),
  createBatch: () => unavailable("Uploading a batch"),
  scoreInvoice: () => unavailable("Scoring a new invoice"),
  uploadDocument: () => unavailable("Uploading a document"),
};
