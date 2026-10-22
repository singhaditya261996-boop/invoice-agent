"""Evaluation runner (PRD §5). Runs the synthetic dataset through the agent, scores it against
ground truth, and writes a report to eval/results/<run>/.

    python -m eval.run_eval --mode offline                          # rules only, free
    python -m eval.run_eval --estimate --input documents            # projected live cost, free
    python -m eval.run_eval --simulate-extraction-errors 0.3        # robustness, free
    python -m eval.run_eval --mode live --input documents --max-cost-usd 40   # the PRD protocol (paid)

Invoices are processed in dataset order within each supplier, and suppliers run in parallel.
Duplicate detection only ever compares invoices from the same supplier, so results match a
fully sequential run (tests/test_eval.py checks this).
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from datetime import datetime, timezone
from pathlib import Path

from app.agent.classifier import CALIBRATION_PATH, Calibrator
from app.agent.llm import ClaudeLLM, FixtureStore, GeminiLLM, ReplayLLM
from app.agent.normalize import supplier_key
from app.agent.pipeline import InvoiceAgent
from app.agent.tools import DataStore
from app.config import RunMode, Settings
from app.metrics import llm_usage
from app.models import Action, InvoiceResult
from data.generator.dataset import Dataset, stratified_sample
from data.generator.generate import DEFAULT_OUT
from eval.scoring import THRESHOLDS, calibration_buckets, calibration_error, fit_calibration, score
from eval.simulate import SimulatedLLM

RESULTS_DIR = Path(__file__).resolve().parent / "results"
CHARS_PER_TOKEN = 3.5  # conservative for JSON-heavy prompts
# Adaptive thinking spend per call at the configured effort is unknown until measured: bracket it.
THINKING_TOKENS = {"extract": (0, 1500), "gr_notes": (0, 400), "classify": (0, 600), "brief": (0, 800)}


# ---------------------------------------------------------------------------- selection


select = stratified_sample


# ---------------------------------------------------------------------------- running


class Run:
    def __init__(self, args: argparse.Namespace, ds: Dataset) -> None:
        self.args = args
        self.ds = ds
        mode = RunMode.OFFLINE if args.estimate or args.simulate_extraction_errors is not None else RunMode(args.mode)
        self.settings = Settings(mode=mode, llm_effort=args.effort, llm_provider=args.provider,
                                 reuse_recorded=args.reuse_recorded,
                                 **({"google_model": args.model} if args.provider == "google" and args.model
                                    else {"llm_model": args.model} if args.model else {}))
        self.name = args.name or "-".join(filter(None, [
            "estimate" if args.estimate else None,
            f"simulated-errors-{args.simulate_extraction_errors:g}" if args.simulate_extraction_errors is not None
            else None,
            None if args.estimate or args.simulate_extraction_errors is not None else mode.value,
            args.provider if mode == RunMode.LIVE and args.provider != "anthropic" else None,
            args.input, f"n{args.limit}" if args.limit else None,
        ]))
        self.out = RESULTS_DIR / self.name
        self.docs = select(ds, args.limit)
        self.sources = self._sources()
        self.truth_by_text: dict[str, list] = defaultdict(list)
        for d in ds.invoices:
            if isinstance(self.sources.get(d.doc_id), str):
                self.truth_by_text[self.sources[d.doc_id]].append((d.doc_id, d.invoice))
        self.simulated = args.estimate or args.simulate_extraction_errors is not None
        # With --reuse-recorded the shared demo-fixture store is both source and destination, so
        # successive pilots accumulate instead of re-paying for invoices already measured.
        self.fixtures = FixtureStore(
            self.settings.fixtures_path if args.reuse_recorded else self.out / "llm_responses.json",
            autosave=False) if mode == RunMode.LIVE else None
        self.client = None
        if mode == RunMode.LIVE and self.settings.llm_provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(max_retries=6)
        self.calibrator = Calibrator() if args.no_calibration else Calibrator.load()
        self.llms: list = []
        self.results: dict[str, InvoiceResult] = {}
        self.stopped_for_budget = False
        self._lock = threading.Lock()

    def _sources(self) -> dict[str, object]:
        inv = {d.doc_id: d.invoice for d in self.ds.invoices}
        if self.args.input == "structured":
            return {d: inv[d] for d in self.docs}
        return {d: (DEFAULT_OUT / "documents" / f"{d}.txt").read_text() for d in self.docs}

    def _llm(self, group_index: int):
        s = self.settings
        if self.simulated:
            llm = SimulatedLLM(self.truth_by_text, self.args.simulate_extraction_errors or 0.0,
                               seed=self.args.seed + group_index)
        elif s.mode == RunMode.LIVE:
            llm = GeminiLLM(s, fixtures=self.fixtures) if s.llm_provider == "google" \
                else ClaudeLLM(s, client=self.client, fixtures=self.fixtures)
        elif s.mode == RunMode.DEMO:
            llm = ReplayLLM(s)
        else:
            return None
        self.llms.append(llm)
        return llm

    def execute(self) -> None:
        by_supplier: dict[str, list[str]] = defaultdict(list)
        truth = {d.doc_id: d.invoice for d in self.ds.invoices}
        for d in self.docs:
            by_supplier[supplier_key(truth[d].supplier_name)].append(d)
        groups = list(by_supplier.values())
        start = time.monotonic()
        workers = 1 if self.settings.mode == RunMode.OFFLINE and not self.simulated else self.args.workers
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in [pool.submit(self._run_group, i, g) for i, g in enumerate(groups)]:
                future.result()
        self.elapsed = time.monotonic() - start
        self.results = {d: self.results[d] for d in self.docs if d in self.results}
        if self.fixtures:
            self.fixtures.flush()

    def _run_group(self, index: int, doc_ids: list[str]) -> None:
        agent = InvoiceAgent(DataStore(self.ds.purchase_orders, self.ds.goods_receipts), self.settings,
                             self._llm(index), self.calibrator)
        for doc_id in doc_ids:
            if self.stopped_for_budget:
                return
            result = agent.process(self.sources[doc_id], doc_id)
            with self._lock:
                self.results[doc_id] = result
                done = len(self.results)
                if self.settings.mode == RunMode.LIVE:
                    spent = llm_usage([c for r in self.results.values() for c in r.llm_calls], done, self.settings)
                    if spent.cost_usd >= self.args.max_cost_usd:
                        self.stopped_for_budget = True
                    if done % 10 == 0 or self.stopped_for_budget:
                        print(f"  {done}/{len(self.docs)} invoices, ${spent.cost_usd:.2f} spent", flush=True)
                    if done % 50 == 0 and self.fixtures:
                        self.fixtures.flush()


# ---------------------------------------------------------------------------- analysis


def cross_fitted_calibration(results: dict[str, InvoiceResult], ds: Dataset) -> dict:
    """Fit calibration on half the invoices, measure on the other half, and swap (no leakage)."""
    labels = {l.doc_id: l for l in ds.labels}
    pairs = [(r.classification.raw_confidence or 0.0, r.classification.code == labels[d].code)
             for d, r in results.items()]
    halves = [pairs[0::2], pairs[1::2]]
    calibrated = []
    for fit_on, apply_to in ((halves[0], halves[1]), (halves[1], halves[0])):
        cal = Calibrator(fit_calibration(fit_on))
        calibrated += [(cal(x), ok) for x, ok in apply_to]
    buckets = calibration_buckets(calibrated)
    return {"error": calibration_error(buckets), "buckets": buckets}


def robustness(run: Run) -> dict | None:
    perturbations = {d: p for llm in run.llms if isinstance(llm, SimulatedLLM) for d, p in llm.perturbations.items()}
    if not run.args.simulate_extraction_errors:
        return None
    labels = {l.doc_id: l for l in run.ds.labels}
    rows = []
    for doc_id, p in perturbations.items():
        r = run.results[doc_id]
        outcome = "manual_entry" if r.extraction.needs_manual_entry else r.classification.action.value
        rows.append({"doc_id": doc_id, "kind": p.kind, "field": p.field, "before": p.before, "after": p.after,
                     "material": p.material, "outcome": outcome, "code": r.classification.code.value
                     if r.classification.code else None, "label": labels[doc_id].code.value})
    unsafe = [r for r in rows if r["material"] and r["outcome"] == Action.AUTO_APPROVE.value]
    by_kind: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_kind[r["kind"]][r["outcome"]] += 1
    return {
        "perturbed_invoices": len(rows),
        "material_misreads": sum(r["material"] for r in rows),
        "caught": sum(r["material"] and r["outcome"] != Action.AUTO_APPROVE.value for r in rows),
        "auto_approved_with_material_misread": unsafe,
        "outcomes_by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
    }


def estimate(run: Run) -> dict:
    requests = [q for llm in run.llms if isinstance(llm, SimulatedLLM) for q in llm.requests]
    price_in, price_out = run.settings.llm_prices_usd_per_mtok.get(run.settings.model_name, (5.0, 25.0))
    by_task = {}
    for task in sorted({q.task for q in requests}):
        qs = [q for q in requests if q.task == task]
        tin = sum(q.input_chars for q in qs) / CHARS_PER_TOKEN
        tout = sum(q.expected_output_chars for q in qs) / CHARS_PER_TOKEN
        think_lo, think_hi = (len(qs) * t for t in THINKING_TOKENS.get(task, (0, 500)))
        by_task[task] = {
            "calls": len(qs), "input_tokens": int(tin), "output_tokens": int(tout),
            "thinking_tokens_range": [think_lo, think_hi],
            "cost_usd_range": [round((tin * price_in + (tout + think_lo) * price_out) / 1e6, 2),
                               round((tin * price_in + (tout + think_hi) * price_out) / 1e6, 2)],
        }
    lo = sum(t["cost_usd_range"][0] for t in by_task.values())
    hi = sum(t["cost_usd_range"][1] for t in by_task.values())
    n = len(run.docs)
    return {
        "model": run.settings.model_name, "effort": run.settings.llm_effort, "input": run.args.input, "invoices": n,
        "by_task": by_task, "total_cost_usd_range": [round(lo, 2), round(hi, 2)],
        "cost_per_invoice_gbp_range": [round(lo / n * run.settings.gbp_per_usd, 4),
                                       round(hi / n * run.settings.gbp_per_usd, 4)],
        "assumptions": [f"{CHARS_PER_TOKEN} characters per token", "thinking tokens bracketed per task: "
                        + ", ".join(f"{k} {a}-{b}" for k, (a, b) in THINKING_TOKENS.items()),
                        f"list prices {price_in}/{price_out} USD per million input/output tokens",
                        f"GBP at {run.settings.gbp_per_usd} per USD",
                        "call counts from a full pipeline run with extraction answered correctly"],
    }


# ---------------------------------------------------------------------------- report


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.2%}" if v <= 1 else f"{v:.3f}"
    return str(v)


def write_report(run: Run, scored: dict, cross: dict, robust: dict | None) -> str:
    m, a, s = scored["metrics"], run.args, run.settings
    lines = [
        f"# Evaluation report: {run.name}", "",
        f"- **Mode:** {s.mode.value}" + (" (simulated extraction)" if run.simulated else ""),
        f"- **Input:** {a.input} ({len(run.results)} of {len(run.ds.invoices)} invoices"
        + (", stopped at budget cap" if run.stopped_for_budget else "") + ")",
        f"- **Model:** {s.model_name} ({s.llm_provider})" if s.mode == RunMode.LIVE else "- **Model:** none",
        f"- **Calibration:** {'fitted table ' + CALIBRATION_PATH.name if run.calibrator.points != Calibrator().points else 'none (identity)'}",
        f"- **Run at:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, {run.elapsed:.1f}s wall clock", "",
        "## Results against PRD thresholds (§5.2)", "",
        "| Metric | Result | Target | Pass |", "|---|---|---|---|",
    ]
    for k, (op, t) in THRESHOLDS.items():
        v = m[k]
        target = {"median_latency_s": f"{op} {t}s", "cost_per_invoice_gbp": f"{op} £{t}"}.get(k, f"{op} {t:.1%}")
        value = _fmt(v) if k not in ("median_latency_s", "cost_per_invoice_gbp") else \
            ("n/a" if v is None else (f"{v:.3f}s" if k == "median_latency_s" else f"£{v:.4f}"))
        ok = scored["pass"][k]
        lines.append(f"| {k.replace('_', ' ')} | {value} | {target} | {'n/a' if ok is None else '✅' if ok else '❌'} |")
    p = scored["product"]
    lines += ["", f"Also: action accuracy {_fmt(m['action_accuracy'])}, auto-reject precision "
              f"{_fmt(m['auto_reject_precision'])}, false approvals {len(p['false_approvals'])}.", "",
              "## Product metrics (§1.6)", "",
              f"- Auto-resolution rate: **{p['auto_resolution_rate']:.1%}** of exceptions (target 40–60%)",
              f"- Straight-through rate: {p['straight_through_rate']:.1%} of all invoices decided without a human",
              f"- Actions: {p['by_action']}", ""]

    if scored["extraction"]:
        e = scored["extraction"]
        lines += ["## Extraction", "",
                  f"- Field accuracy: {_fmt(e['field_accuracy'])} (on invoices extracted: "
                  f"{_fmt(e['field_accuracy_when_extracted'])})",
                  f"- Flagged for manual entry: {_fmt(e['manual_entry_rate'])}",
                  f"- Invoices with any wrong field: {e['invoices_with_errors']}",
                  f"- Most-missed fields: {e['wrong_fields'] or 'none'}", ""]

    if robust:
        lines += ["## Robustness to extraction errors (simulated)", "",
                  f"{robust['perturbed_invoices']} invoices had one field misread "
                  f"({robust['material_misreads']} in a field that affects payment). The simulated model "
                  "reported 95% confidence on every extraction, as an overconfident model would.", "",
                  f"- Material misreads caught (manual entry or escalation): **{robust['caught']} of "
                  f"{robust['material_misreads']}**",
                  f"- Auto-approved despite a material misread: **{len(robust['auto_approved_with_material_misread'])}**",
                  "", "| Misread | Outcomes |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in robust["outcomes_by_kind"].items()]
        for u in robust["auto_approved_with_material_misread"][:10]:
            lines.append(f"\n- ⚠️ {u['doc_id']}: {u['field']} {u['before']} → {u['after']}")
        lines.append("")

    lines += ["## By exception category", "", "| Code | n | Precision | Recall |", "|---|---|---|---|"]
    lines += [f"| {c} | {v['n']} | {_fmt(v['precision'])} | {_fmt(v['recall'])} |"
              for c, v in scored["per_code"].items()]
    lines += ["", "## Edge cases (§5.1)", "", "| Tag | n | Classification | Action |", "|---|---|---|---|"]
    lines += [f"| {t} | {v['n']} | {_fmt(v['classification_accuracy'])} | {_fmt(v['action_accuracy'])} |"
              for t, v in scored["edge_cases"].items()]

    cal = scored["calibration"]
    lines += ["", "## Calibration (D-04)", "",
              f"Calibration error (PRD definition, mean gap per bucket): {_fmt(m['calibration_error'])}; "
              f"size-weighted ECE: {_fmt(cal['ece_weighted'])}. After cross-fitted isotonic calibration: "
              f"{_fmt(cross['error'])}.", "",
              "| Confidence | n | Mean stated | Actual accuracy |", "|---|---|---|---|"]
    lines += [f"| {b['range']} | {b['n']} | {b['mean_confidence']:.3f} | {b['accuracy']:.3f} |" for b in cal["buckets"]]

    llm = scored["llm"]
    lines += ["", "## Cost and latency", "",
              f"- LLM calls: {llm['calls']} ({llm['failed_calls']} fell back to rules), "
              f"{llm['input_tokens']:,} input / {llm['output_tokens']:,} output tokens",
              f"- Cost: ${llm['cost_usd']:.2f} (£{llm['cost_gbp']:.2f}), £{llm['cost_per_invoice_gbp']:.4f} per invoice",
              latency_line(scored, llm),
              "", f"## Failures ({len(scored['failures'])})", ""]
    if scored["failures"]:
        lines += ["| Doc | Expected | Got | Conf. | Detail |", "|---|---|---|---|---|"]
        lines += [f"| {f['doc_id']} | {f['expected']} ({f['variant']}) | {f['got']} | {f['confidence']:.2f} | "
                  f"{f['detail'][:120]} |" for f in scored["failures"][:40]]
    else:
        lines.append("None.")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in caveats(run)]
    return "\n".join(lines) + "\n"


def latency_line(scored: dict, llm: dict) -> str:
    lat = scored["latency_ms"]
    replayed = f", {llm['cached_calls']} calls replayed from earlier runs" if llm["cached_calls"] else ""
    return (f"- Latency per invoice: median {lat['median']} ms, p90 {lat['p90']} ms "
            f"(measured on the {lat['invoices']} invoices whose model calls ran this time{replayed})")


def caveats(run: Run) -> list[str]:
    out = ["The synthetic data was generated with the same rules the agent applies, so rule-based steps are "
           "expected to score near 100%. Real invoices will be messier. These results are an upper bound "
           "for the deterministic steps and a regression baseline, not a production accuracy estimate."]
    if run.settings.mode == RunMode.OFFLINE and not run.simulated:
        out.append("No LLM was used: extraction was not exercised (structured input), and GR notes, "
                   "root-cause and brief steps used their rule-based fallbacks.")
    if run.simulated:
        out.append("Extraction was simulated, not performed by a model. The simulation tests the safeguards "
                   "around extraction, not extraction quality itself.")
    if any(c.cached for r in run.results.values() for c in r.llm_calls):
        out.append("Some model responses were replayed from earlier runs (--reuse-recorded), so this run's "
                   "accuracy covers every invoice listed but its latency covers only the invoices whose "
                   "calls actually ran.")
    out.append("Calibration can only be meaningfully fitted where the agent makes mistakes. With near-perfect "
               "accuracy every bucket is ~100% accurate, so stated confidence looks under-confident.")
    return out


# ---------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> Run:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=[m.value for m in RunMode], default="offline")
    parser.add_argument("--input", choices=["structured", "documents"], default="structured")
    parser.add_argument("--limit", type=int, help="stratified sample of N invoices (plus duplicate originals)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--provider", choices=["anthropic", "google"], default="anthropic",
                        help="google runs the pipeline on Gemini; results describe that model, not Claude")
    parser.add_argument("--model", default=None, help="override the provider's default model")
    parser.add_argument("--effort", default=Settings().llm_effort)
    parser.add_argument("--max-cost-usd", type=float, default=40.0, help="live mode: stop when spend reaches this")
    parser.add_argument("--estimate", action="store_true", help="project live cost without calling the API")
    parser.add_argument("--simulate-extraction-errors", type=float, metavar="RATE",
                        help="simulated extraction with this share of invoices misread (implies --input documents)")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the run misses its thresholds (for CI)")
    parser.add_argument("--rescore", action="store_true",
                        help="recompute metrics and report from a run's saved results.jsonl; no API calls")
    parser.add_argument("--reuse-recorded", action="store_true",
                        help="replay identical requests recorded by an earlier live run (saves quota/cost)")
    parser.add_argument("--fit-calibration", action="store_true", help=f"write a fitted table to {CALIBRATION_PATH}")
    parser.add_argument("--no-calibration", action="store_true", help="ignore any saved calibration table")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--name")
    args = parser.parse_args(argv)
    if args.simulate_extraction_errors is not None:
        args.input = "documents"

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # API keys for live runs
    ds = Dataset.load(DEFAULT_OUT)
    run = Run(args, ds)
    run.out.mkdir(parents=True, exist_ok=True)
    if args.rescore:
        saved = run.out / "results.jsonl"
        if not saved.exists():
            parser.error(f"no saved results at {saved}")
        run.results = {r.doc_id: r for r in (InvoiceResult.model_validate_json(line)
                                             for line in saved.read_text().splitlines())}
        run.docs = list(run.results)
        run.elapsed = 0.0
        print(f"Rescoring {run.name}: {len(run.results)} invoices from {saved.name}")
    else:
        print(f"Running {run.name}: {len(run.docs)} invoices")
        run.execute()

    if args.estimate:
        est = estimate(run)
        (run.out / "estimate.json").write_text(json.dumps(est, indent=2) + "\n")
        lo, hi = est["total_cost_usd_range"]
        print(f"Estimated live cost for {est['invoices']} invoices ({est['model']}, effort {est['effort']}): "
              f"${lo:.2f}–${hi:.2f}, £{est['cost_per_invoice_gbp_range'][0]:.3f}–"
              f"£{est['cost_per_invoice_gbp_range'][1]:.3f} per invoice")
        for task, t in est["by_task"].items():
            print(f"  {task:<9} {t['calls']:>4} calls  ${t['cost_usd_range'][0]:.2f}–${t['cost_usd_range'][1]:.2f}")
        return run

    scored = score(run.results, ds, run.settings)
    cross = cross_fitted_calibration(run.results, ds)
    robust = robustness(run)
    (run.out / "metrics.json").write_text(json.dumps(
        {"run": run.name, "args": vars(args), "elapsed_s": round(run.elapsed, 1), **scored,
         "calibration_cross_fitted": cross, "robustness": robust}, indent=2, default=str) + "\n")
    with (run.out / "results.jsonl").open("w") as f:
        for r in run.results.values():
            f.write(r.model_dump_json() + "\n")
    (run.out / "report.md").write_text(write_report(run, scored, cross, robust))

    if args.fit_calibration:
        labels = {l.doc_id: l for l in ds.labels}
        points = fit_calibration([(r.classification.raw_confidence or 0.0, r.classification.code == labels[d].code)
                                  for d, r in run.results.items()])
        CALIBRATION_PATH.write_text(json.dumps({"fitted_on": run.name, "invoices": len(run.results),
                                                "points": points}, indent=2) + "\n")
        print(f"Wrote calibration table ({len(points)} points) to {CALIBRATION_PATH}")

    m = scored["metrics"]
    shown = {k: (f"{m[k]:.3f}s" if k == "median_latency_s" else f"£{m[k]:.4f}" if k == "cost_per_invoice_gbp"
                 else _fmt(m[k])) for k in THRESHOLDS if m[k] is not None}
    print("  " + ", ".join(f"{k}={v}" for k, v in shown.items()))
    if robust:
        print(f"  misreads caught {robust['caught']}/{robust['material_misreads']}, unsafe approvals "
              f"{len(robust['auto_approved_with_material_misread'])}")
    print(f"Report: {run.out / 'report.md'}")

    if args.check:
        _check(run, scored, robust)
    return run


# Safety properties hold under every condition, including deliberate misreads. Accuracy metrics do
# not: a run that misreads half its invoices is *expected* to classify them wrong, and what matters
# there is that none of them is paid.
SAFETY_METRICS = ("auto_resolution_precision", "escalation_recall")

# Calibration is a known-open target: no table is installed, because fitting one needs a sample
# containing real mistakes (D-04). The report still shows it failing — gating CI on it would mean a
# permanently red build, which teaches people to ignore the signal.
NOT_GATED = ("calibration_error",)


def _check(run: Run, scored: dict, robust: dict | None) -> None:
    relevant = SAFETY_METRICS if run.args.simulate_extraction_errors else \
        tuple(k for k in THRESHOLDS if k not in NOT_GATED)
    failures = [f"{k} = {_fmt(scored['metrics'][k])} (target {THRESHOLDS[k][0]} {THRESHOLDS[k][1]})"
                for k in relevant if scored["pass"].get(k) is False]
    if scored["product"]["false_approvals"]:
        failures.append(f"{len(scored['product']['false_approvals'])} false approvals: "
                        f"{', '.join(scored['product']['false_approvals'][:5])}")
    if robust and robust["auto_approved_with_material_misread"]:
        failures.append(f"{len(robust['auto_approved_with_material_misread'])} invoices auto-approved "
                        "despite a misread that affects payment")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print(f"  checked {len(relevant)} thresholds: all pass")


if __name__ == "__main__":
    main()
