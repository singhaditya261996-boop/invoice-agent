"""Evaluation metrics (PRD §5.2) computed from pipeline results against ground truth."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from app.config import Settings
from app.metrics import llm_usage, summarize
from app.models import Action, ExceptionCode as EC, Invoice, InvoiceResult
from data.generator.dataset import Dataset, GroundTruth

# PRD §5.2 pass thresholds: (comparison, threshold)
THRESHOLDS = {
    "extraction_accuracy": (">", 0.95),
    "match_accuracy": (">", 0.98),
    "classification_accuracy": (">", 0.90),
    "calibration_error": ("<", 0.05),
    "auto_resolution_precision": (">", 0.995),
    "escalation_recall": (">", 0.99),
    "median_latency_s": ("<", 30),
    "cost_per_invoice_gbp": ("<", 0.15),
}

SAFE_TO_APPROVE = {EC.CLEAN, EC.E01}
HEADER_FIELDS = ("invoice_number", "supplier_name", "po_reference", "invoice_date", "due_date",
                 "subtotal", "tax_amount", "total_amount", "currency")
LINE_FIELDS = ("description", "quantity", "unit_price", "tax", "total")


def passes(metric: str, value: float | None) -> bool | None:
    if value is None or metric not in THRESHOLDS:
        return None
    op, threshold = THRESHOLDS[metric]
    return value > threshold if op == ">" else value < threshold


# ---------------------------------------------------------------------------- extraction


def _norm(field: str, value):
    if field == "po_reference":
        return (value or "").strip() or None
    if field == "description":
        return " ".join(str(value).split())
    return value


def field_matches(extracted: Invoice | None, truth: Invoice) -> tuple[int, int, list[str]]:
    """(correct, total, wrong_field_names). A missing extraction scores every field wrong."""
    total = len(HEADER_FIELDS) + len(LINE_FIELDS) * len(truth.line_items)
    if extracted is None:
        return 0, total, ["<not extracted>"]
    wrong = [f for f in HEADER_FIELDS if _norm(f, getattr(extracted, f)) != _norm(f, getattr(truth, f))]
    for i, t in enumerate(truth.line_items):
        e = extracted.line_items[i] if i < len(extracted.line_items) else None
        wrong += [f"line{i + 1}.{f}" for f in LINE_FIELDS
                  if e is None or _norm(f, getattr(e, f)) != _norm(f, getattr(t, f))]
    extra = len(extracted.line_items) - len(truth.line_items)
    if extra > 0:  # hallucinated lines count against accuracy
        total += extra * len(LINE_FIELDS)
        wrong += [f"extra_line{i + 1}.{f}" for i in range(extra) for f in LINE_FIELDS]
    return total - len(wrong), total, sorted(set(wrong))


# ---------------------------------------------------------------------------- calibration


def calibration_buckets(pairs: list[tuple[float, bool]], n_buckets: int = 10) -> list[dict]:
    """Decile buckets of stated confidence vs observed accuracy (PRD §5.3)."""
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for conf, correct in pairs:
        buckets[min(int(conf * n_buckets), n_buckets - 1)].append((conf, correct))
    return [{
        "range": f"{b / n_buckets:.1f}-{(b + 1) / n_buckets:.1f}",
        "n": len(items),
        "mean_confidence": round(sum(c for c, _ in items) / len(items), 4),
        "accuracy": round(sum(ok for _, ok in items) / len(items), 4),
    } for b, items in sorted(buckets.items())]


def calibration_error(buckets: list[dict]) -> float | None:
    """PRD definition: mean absolute gap between confidence and accuracy across non-empty buckets."""
    return round(sum(abs(b["mean_confidence"] - b["accuracy"]) for b in buckets) / len(buckets), 4) \
        if buckets else None


def expected_calibration_error(buckets: list[dict]) -> float | None:
    """Standard ECE (bucket gaps weighted by size), reported alongside the PRD's unweighted version."""
    n = sum(b["n"] for b in buckets)
    return round(sum(b["n"] * abs(b["mean_confidence"] - b["accuracy"]) for b in buckets) / n, 4) if n else None


def fit_calibration(pairs: list[tuple[float, bool]], prior_strength: float = 2.0) -> list[tuple[float, float]]:
    """Isotonic (monotone) map from raw score to accuracy, via pool-adjacent-violators.

    Each block's accuracy is smoothed towards 0.5 with a Beta prior, so a small, perfect block
    cannot claim certainty. Returns the points for app.agent.classifier.Calibrator.
    """
    if not pairs:
        return [(0.0, 0.0), (1.0, 1.0)]
    by_score: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for x, ok in pairs:
        by_score[x][0] += ok
        by_score[x][1] += 1
    blocks: list[list[float]] = []  # [sum_x, sum_correct, n] over runs of distinct scores
    for x in sorted(by_score):
        correct, n = by_score[x]
        blocks.append([x * n, correct, n])
        # Pool violators and ties, so equal-accuracy runs share one smoothed estimate.
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] >= blocks[-1][1] / blocks[-1][2]:
            sx, sc, n = blocks.pop()
            blocks[-1] = [blocks[-1][0] + sx, blocks[-1][1] + sc, blocks[-1][2] + n]
    points = [(round(sx / n, 4), round((sc + prior_strength / 2) / (n + prior_strength), 4)) for sx, sc, n in blocks]
    ys = [y for _, y in points]
    for i in range(1, len(ys)):  # smoothing can break monotonicity slightly; restore it
        ys[i] = max(ys[i], ys[i - 1])
    points = [(x, y) for (x, _), y in zip(points, ys)]
    return [(0.0, ys[0])] + points + [(1.0, ys[-1])]


# ---------------------------------------------------------------------------- scoring


def score(results: dict[str, InvoiceResult], ds: Dataset, settings: Settings) -> dict:
    labels: dict[str, GroundTruth] = {l.doc_id: l for l in ds.labels if l.doc_id in results}
    truth: dict[str, Invoice] = {d.doc_id: d.invoice for d in ds.invoices if d.doc_id in results}
    order = [d for d in results if d in labels]
    rs = [results[d] for d in order]
    ls = [labels[d] for d in order]
    n = len(rs)

    def rate(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    # Extraction (only meaningful when the LLM read documents)
    llm_extracted = [d for d in order if results[d].extraction.method == "llm"]
    extraction = None
    if llm_extracted:
        per_doc = {d: field_matches(results[d].extraction.invoice, truth[d]) for d in llm_extracted}
        got = [d for d in llm_extracted if results[d].extraction.invoice is not None]
        extraction = {
            "field_accuracy": rate(sum(c for c, _, _ in per_doc.values()), sum(t for _, t, _ in per_doc.values())),
            "field_accuracy_when_extracted": rate(sum(per_doc[d][0] for d in got), sum(per_doc[d][1] for d in got)),
            "manual_entry_rate": rate(sum(results[d].extraction.needs_manual_entry for d in llm_extracted),
                                      len(llm_extracted)),
            "invoices_with_errors": sum(bool(w) for _, _, w in per_doc.values()),
            "wrong_fields": dict(Counter(f.split(".")[-1] for _, _, w in per_doc.values() for f in w).most_common()),
        }

    classified = [(r, l) for r, l in zip(rs, ls) if r.match is not None]  # not sent to manual entry
    match_ok = sum((r.match.matched_po.po_number if r.match.matched_po else None) == l.true_po_number
                   for r, l in classified)
    code_ok = [r.classification.code == l.code for r, l in zip(rs, ls)]
    action_ok = [r.classification.action == l.action for r, l in zip(rs, ls)]

    approved = [(r, l) for r, l in zip(rs, ls) if r.classification.action == Action.AUTO_APPROVE]
    rejected = [(r, l) for r, l in zip(rs, ls) if r.classification.action == Action.AUTO_REJECT]
    problematic = [(r, l) for r, l in zip(rs, ls) if l.code not in SAFE_TO_APPROVE]
    false_approvals = [l.doc_id for r, l in approved if l.code not in SAFE_TO_APPROVE]

    buckets = calibration_buckets([(r.classification.confidence, ok) for r, ok in zip(rs, code_ok)])
    raw_buckets = calibration_buckets([(r.classification.raw_confidence or 0.0, ok) for r, ok in zip(rs, code_ok)])

    usage = llm_usage([c for r in rs for c in r.llm_calls], n, settings)
    # Latency is only meaningful for invoices whose model calls actually ran this time: an invoice
    # served from recorded responses returns in milliseconds and would flatter the median.
    timed = [r for r in rs if not any(c.cached for c in r.llm_calls)]
    latencies = sorted(r.latency_ms for r in timed)

    confusion: dict[str, Counter] = defaultdict(Counter)
    for r, l in zip(rs, ls):
        confusion[l.code.value][r.classification.code.value if r.classification.code else "unclassified"] += 1
    per_code = {}
    for code in sorted({l.code.value for l in ls}):
        tp = confusion[code][code]
        predicted = sum(c[code] for c in confusion.values())
        actual = sum(confusion[code].values())
        per_code[code] = {"n": actual, "precision": rate(tp, predicted), "recall": rate(tp, actual)}

    edge = {}
    for tag in sorted({t for l in ls for t in l.edge_cases}):
        idx = [i for i, l in enumerate(ls) if tag in l.edge_cases]
        edge[tag] = {"n": len(idx), "classification_accuracy": rate(sum(code_ok[i] for i in idx), len(idx)),
                     "action_accuracy": rate(sum(action_ok[i] for i in idx), len(idx))}

    failures = []
    for r, l, ok_c, ok_a in zip(rs, ls, code_ok, action_ok):
        if ok_c and ok_a:
            continue
        c = r.classification
        why = (r.extraction.issues or ["manual entry"])[0] if r.match is None else \
            "; ".join(d.detail for d in r.validation.discrepancies[:2]) or "no discrepancies found"
        failures.append({
            "doc_id": l.doc_id, "expected": f"{l.code.value}/{l.action.value}", "variant": l.variant,
            "got": f"{c.code.value if c.code else 'unclassified'}/{c.action.value}", "confidence": c.confidence,
            "detail": why,
        })

    metrics = {
        "invoices": n,
        "extraction_accuracy": extraction["field_accuracy"] if extraction else None,
        "match_accuracy": rate(match_ok, len(classified)),
        "classification_accuracy": rate(sum(code_ok), n),
        "action_accuracy": rate(sum(action_ok), n),
        "calibration_error": calibration_error(buckets),
        "auto_resolution_precision": rate(len(approved) - len(false_approvals), len(approved)),
        "auto_reject_precision": rate(sum(l.code == EC.E04 for _, l in rejected), len(rejected)),
        "escalation_recall": rate(sum(r.classification.action != Action.AUTO_APPROVE for r, _ in problematic),
                                  len(problematic)),
        "median_latency_s": round(median(latencies) / 1000, 3) if latencies else None,
        "latency_measured_on": len(timed),
        "cost_per_invoice_gbp": round(usage.cost_per_invoice_gbp, 5),
    }
    product = summarize(rs, {}, settings)
    return {
        "metrics": metrics,
        "pass": {k: passes(k, v) for k, v in metrics.items() if k in THRESHOLDS},
        "product": {
            "auto_resolution_rate": round(product.auto_resolution_rate, 4),
            "straight_through_rate": round(product.straight_through_rate, 4),
            "false_approvals": false_approvals,
            "by_action": product.by_action,
        },
        "extraction": extraction,
        "calibration": {
            "buckets": buckets,
            "ece_weighted": expected_calibration_error(buckets),
            "raw_buckets": raw_buckets,
        },
        "latency_ms": {"invoices": len(timed),
                       "median": latencies[len(timed) // 2] if timed else None,
                       "p90": latencies[int(len(timed) * 0.9)] if timed else None,
                       "max": latencies[-1] if timed else None},
        "llm": usage.model_dump(),
        "per_code": per_code,
        "confusion": {k: dict(v) for k, v in sorted(confusion.items())},
        "edge_cases": edge,
        "failures": failures,
    }
