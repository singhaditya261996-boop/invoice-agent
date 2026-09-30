import argparse

import pytest

from app.agent.classifier import Calibrator
from app.agent.pipeline import InvoiceAgent
from app.agent.tools import DataStore
from app.config import RunMode, Settings
from data.generator.dataset import Dataset
from data.generator.generate import DEFAULT_OUT
from eval.run_eval import Run, estimate, robustness, select
from eval.scoring import field_matches, fit_calibration, score
from eval.simulate import SimulatedLLM


@pytest.fixture(scope="module")
def ds():
    return Dataset.load(DEFAULT_OUT)


def args(**overrides):
    base = dict(mode="offline", input="structured", limit=None, workers=4, provider="anthropic", model=None,
                effort="medium",
                max_cost_usd=1.0, estimate=False, simulate_extraction_errors=None, fit_calibration=False,
                no_calibration=True, seed=0, name="test", reuse_recorded=False, rescore=False)
    return argparse.Namespace(**base | overrides)


def test_parallel_supplier_groups_match_a_sequential_run(ds):
    run = Run(args(simulate_extraction_errors=0.0, input="documents", workers=8), ds)
    run.execute()

    sequential = InvoiceAgent(DataStore(ds.purchase_orders, ds.goods_receipts), run.settings,
                              SimulatedLLM(run.truth_by_text, 0.0), Calibrator())
    for d in run.docs:
        got, want = run.results[d].classification, sequential.process(run.sources[d], d).classification
        assert (got.code, got.action, got.confidence) == (want.code, want.action, want.confidence), d


def test_stratified_sample_covers_every_variant_and_keeps_duplicate_originals(ds):
    docs = set(select(ds, 40))
    labels = {l.doc_id: l for l in ds.labels}
    assert {(l.code, l.variant) for l in ds.labels} == {(labels[d].code, labels[d].variant) for d in docs}
    assert all(labels[d].duplicate_of in docs for d in docs if labels[d].duplicate_of)


def test_offline_scores_perfectly_and_estimate_is_positive(ds):
    run = Run(args(), ds)
    run.execute()
    m = score(run.results, ds, run.settings)["metrics"]
    assert m["classification_accuracy"] == m["auto_resolution_precision"] == m["escalation_recall"] == 1.0

    est_run = Run(args(estimate=True, input="documents", limit=20), ds)
    est_run.execute()
    est = estimate(est_run)
    assert est["by_task"]["extract"]["calls"] == len(est_run.docs)
    assert 0 < est["total_cost_usd_range"][0] < est["total_cost_usd_range"][1]


def test_simulated_misreads_never_lead_to_unsafe_approval(ds):
    run = Run(args(simulate_extraction_errors=1.0, input="documents"), ds)
    run.execute()
    report = robustness(run)
    assert report["perturbed_invoices"] == len(ds.invoices)
    assert report["auto_approved_with_material_misread"] == []
    assert score(run.results, ds, run.settings)["product"]["false_approvals"] == []


@pytest.mark.parametrize("pairs,checks", [
    ([(0.75, True)] * 5 + [(0.98, True)] * 300, [(0.5, 0.99), (0.99, 0.99)]),
    ([(0.5, False)] * 10 + [(0.5, True)] * 10 + [(0.9, True)] * 90 + [(0.9, False)] * 10, [(0.5, 0.5), (0.9, 0.89)]),
])
def test_fit_calibration(pairs, checks):
    cal = Calibrator(fit_calibration(pairs))
    for raw, expected in checks:
        assert cal(raw) == pytest.approx(expected, abs=0.01)
    ys = [y for _, y in cal.points]
    assert ys == sorted(ys)


def test_field_matches(ds):
    truth = ds.invoices[0].invoice
    assert field_matches(truth, truth)[0] == field_matches(truth, truth)[1]
    wrong = truth.model_copy(update={"subtotal": truth.subtotal + 1, "po_reference": ""})
    correct, total, fields = field_matches(wrong, truth)
    expect_po_wrong = bool((truth.po_reference or "").strip())
    assert total - correct == 1 + expect_po_wrong and "subtotal" in fields
    extra = truth.model_copy(update={"line_items": truth.line_items * 2})
    c, t, _ = field_matches(extra, truth)
    assert t - c == 5 * len(truth.line_items)
    assert field_matches(None, truth)[0] == 0
