import { useEffect, useState } from "react";

import { api, type Mode } from "../api";
import { Button, Card, ErrorNote, Field, inputClass, Loading, Segmented } from "../components/ui";
import { date, MODE_LABELS } from "../format";
import { href, useAsync } from "../hooks";

export function BatchesPage() {
  const batches = useAsync(api.batches, [], (bs) => bs.some((b) => b.status !== "complete"));
  const config = useAsync(api.config, []);
  const [mode, setMode] = useState<Mode>("demo");
  const [input, setInput] = useState<"structured" | "documents">("structured");
  const [limit, setLimit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (config.data) setMode(config.data.default_mode);
  }, [config.data]);

  const start = async (create: () => Promise<{ id: string }>) => {
    setBusy(true);
    setError(undefined);
    try {
      const batch = await create();
      window.location.hash = href("batches", batch.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    try {
      const body = JSON.parse(await file.text());
      await start(() => api.createBatch({ ...body, mode: body.mode ?? mode }));
    } catch (e) {
      setError(`Could not read ${file.name}: ${(e as Error).message}`);
    }
  };

  const documentsWarning = input === "documents" && (mode === "offline"
    ? "Without an AI model the documents can't be read, so every invoice will go to manual entry."
    : mode === "demo"
      ? "Demo mode only has cached responses for recorded invoices; the rest go to manual entry."
      : "Live mode reads every document with the AI model. The full dataset costs roughly $7–$33.");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Invoice batches</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Upload a batch of invoices with the purchase orders and goods receipts they should match. The agent approves
          what is clearly safe, rejects clear duplicates, and brings everything else to you with its reasoning.
        </p>
      </div>

      {error && <ErrorNote message={error} />}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Load the synthetic dataset" className="lg:col-span-2">
          <p className="mb-5 text-sm text-ink-2">
            500 fictional UK invoices with 501 purchase orders and 476 goods receipts, covering every exception type and
            some deliberately ambiguous cases.
          </p>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Mode" hint={MODE_LABELS[mode].help}>
              <Segmented label="Mode" value={mode} onChange={setMode}
                options={(["demo", "live", "offline"] as Mode[]).map((m) => ({ value: m, label: MODE_LABELS[m].label }))} />
            </Field>
            <Field label="Invoices as" hint={input === "structured" ? "Already-extracted fields (JSON)."
              : "Text documents the AI model has to read."}>
              <Segmented label="Invoices as" value={input} onChange={setInput}
                options={[{ value: "structured", label: "Structured" }, { value: "documents", label: "Documents" }]} />
            </Field>
            <Field label="Number of invoices" hint="Leave blank for all 500. A smaller sample still covers every scenario.">
              <input className={inputClass} inputMode="numeric" placeholder="All" value={limit}
                onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))} />
            </Field>
          </div>
          {documentsWarning && (
            <p className="mt-4 rounded-lg bg-wash px-3 py-2 text-sm text-ink-2">
              <span aria-hidden className="mr-1.5">ⓘ</span>{documentsWarning}
            </p>
          )}
          <div className="mt-5">
            <Button disabled={busy} onClick={() => start(() => api.createDemo({
              mode, input, limit: limit ? Number(limit) : undefined,
            }))}>
              {busy ? "Starting…" : "Start batch"}
            </Button>
          </div>
        </Card>

        <Card title="Upload your own batch">
          <p className="mb-4 text-sm text-ink-2">
            A JSON file with <code className="text-xs">purchase_orders</code>, <code className="text-xs">goods_receipts</code>
            {" "}and <code className="text-xs">invoices</code> (each with <code className="text-xs">invoice</code> fields or
            {" "}<code className="text-xs">document</code> text). Uses the mode selected on the left.
          </p>
          <label className="inline-flex cursor-pointer items-center rounded-lg border border-line bg-raised px-3.5 py-2
            text-sm font-medium hover:bg-wash">
            Choose JSON file
            <input type="file" accept="application/json,.json" className="sr-only"
              onChange={(e) => onUpload(e.target.files?.[0])} />
          </label>
        </Card>
      </div>

      <Card title="Batches">
        {batches.error && <ErrorNote message={batches.error} />}
        {!batches.data ? <Loading /> : batches.data.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">No batches yet. Start one above.</p>
        ) : (
          <div className="-mx-5 -my-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="px-5 py-2.5 font-medium">Batch</th>
                  <th className="px-3 py-2.5 font-medium">Mode</th>
                  <th className="px-3 py-2.5 font-medium">Progress</th>
                  <th className="px-3 py-2.5 text-right font-medium">Escalated</th>
                  <th className="px-5 py-2.5 text-right font-medium">Waiting for review</th>
                </tr>
              </thead>
              <tbody>
                {batches.data.map((b) => (
                  <tr key={b.id} className="border-b border-line last:border-0 hover:bg-wash">
                    <td className="px-5 py-3">
                      <a className="font-medium hover:underline" href={href("batches", b.id)}>{b.name}</a>
                      <div className="text-xs text-muted">{b.id} · {date(b.created_at)}</div>
                    </td>
                    <td className="px-3 py-3 text-ink-2">{MODE_LABELS[b.mode].label}</td>
                    <td className="px-3 py-3">
                      <Progress done={b.processed} total={b.total} complete={b.status === "complete"} />
                    </td>
                    <td className="tabular px-3 py-3 text-right">{b.escalated}</td>
                    <td className="tabular px-5 py-3 text-right font-medium">{b.pending_review}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export function Progress({ done, total, complete }: { done: number; total: number; complete: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-wash">
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
      </div>
      <span className="tabular text-xs text-ink-2">{complete ? `${total} done` : `${done}/${total}`}</span>
    </div>
  );
}
