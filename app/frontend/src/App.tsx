import { useEffect, useState } from "react";

import { api, STATIC_DEMO } from "./api";
import { Drawer, ErrorNote, Loading } from "./components/ui";
import { CODE_LABELS, pct } from "./format";
import { href, useAsync, useRoute } from "./hooks";
import { BatchPage } from "./pages/BatchPage";
import { BatchesPage } from "./pages/BatchesPage";
import { InvoicePage } from "./pages/InvoicePage";

export default function App() {
  const route = useRoute();
  const [showRules, setShowRules] = useState(false);

  let page;
  if (STATIC_DEMO && route.length === 0) {
    page = <OpenDemoBatch />;
  } else if (route[0] === "batches" && route[1] && route[2] === "invoices" && route[3]) {
    page = <InvoicePage batchId={route[1]} docId={route[3]} />;
  } else if (route[0] === "batches" && route[1]) {
    const tab = route[2] === "dashboard" ? "dashboard" : route[2] === "policy" ? "policy" : "queue";
    page = <BatchPage batchId={route[1]} tab={tab} />;
  } else {
    page = <BatchesPage />;
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <a href={href()} className="flex items-center gap-2.5 font-semibold">
            <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-accent text-xs text-accent-ink">IA</span>
            InvoiceAgent
            <span className="hidden text-sm font-normal text-muted sm:inline">AP exception triage</span>
          </a>
          {STATIC_DEMO && (
            <span className="hidden rounded-full bg-wash px-3 py-1 text-xs text-ink-2 md:inline">
              Hosted demo · recorded batch · your decisions stay in this browser
            </span>
          )}
          <button onClick={() => setShowRules(true)} className="text-sm text-ink-2 underline-offset-4 hover:text-ink
            hover:underline">
            How the agent decides
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{page}</main>
      {showRules && <RulesDrawer onClose={() => setShowRules(false)} />}
    </div>
  );
}

/** The hosted demo has exactly one batch, so skip the batch-setup screen and open its queue. */
function OpenDemoBatch() {
  const { data, error } = useAsync(api.batches, []);
  useEffect(() => {
    if (data?.[0]) window.location.replace(href("batches", data[0].id));
  }, [data]);
  return error ? <ErrorNote message={error} /> : <Loading label="Opening the demo batch…" />;
}


function RulesDrawer({ onClose }: { onClose: () => void }) {
  const { data: c, error } = useAsync(api.config, []);
  return (
    <Drawer title="How the agent decides" onClose={onClose}>
      {error && <ErrorNote message={error} />}
      {!c ? <Loading /> : (
        <div className="space-y-6 text-sm leading-relaxed">
          <section>
            <h3 className="mb-2 font-semibold">Every invoice goes through five steps</h3>
            <ol className="list-decimal space-y-1 pl-5 text-ink-2">
              <li><b className="text-ink">Extract</b> the fields (the AI model reads documents; structured data is used as-is).</li>
              <li><b className="text-ink">Match</b> to a purchase order: on the PO number, or by supplier, amount and lines
                (score of at least {c.min_match_score}).</li>
              <li><b className="text-ink">Validate</b> against the PO and goods receipt: amount, quantities, VAT at
                {" "}{pct(Number(c.vat_rate))}, supplier, PO status, duplicates.</li>
              <li><b className="text-ink">Classify</b> the result into one exception type, with a confidence score.</li>
              <li><b className="text-ink">Report</b>: approve, reject, or escalate to you with a brief.</li>
            </ol>
          </section>
          <section>
            <h3 className="mb-2 font-semibold">What it is allowed to do on its own</h3>
            <ul className="space-y-1.5 text-ink-2">
              <li>Approve clean invoices and{" "}
                {c.auto_resolvable.filter((x) => x !== "E04").map((x) => CODE_LABELS[x].toLowerCase()).join(", ")}
                {" "}only at {pct(c.auto_approve_confidence)} confidence or higher.</li>
              <li>Reject duplicates at {pct(c.auto_reject_duplicate_confidence)} confidence or higher.</li>
              <li>Everything else, and anything it is unsure about, comes to you. The AI model cannot override these
                rules.</li>
              <li>Amount tolerance: {pct(Number(c.tolerance.pct))} or £{c.tolerance.absolute_gbp}, {c.tolerance.rule}.</li>
              <li>Duplicates: same supplier and amount within {c.duplicate_window_days} day(s), the same PO billed twice,
                or the same invoice number.</li>
            </ul>
          </section>
          <section>
            <h3 className="mb-2 font-semibold">Confidence bands</h3>
            <ul className="space-y-1 text-ink-2">
              <li><span className="mr-2 inline-block size-2.5 rounded-full bg-good" />High: {c.confidence_bands.green}</li>
              <li><span className="mr-2 inline-block size-2.5 rounded-full bg-warning" />Medium: {c.confidence_bands.amber}</li>
              <li><span className="mr-2 inline-block size-2.5 rounded-full bg-critical" />Low: {c.confidence_bands.red}</li>
            </ul>
          </section>
          <p className="text-xs text-muted">Model: {c.llm_model}. Server default mode: {c.default_mode}.</p>
        </div>
      )}
    </Drawer>
  );
}
