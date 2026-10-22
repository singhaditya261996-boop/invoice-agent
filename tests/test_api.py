import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import RunMode, Settings
from data.generator.dataset import Dataset
from data.generator.generate import DEFAULT_OUT
from data.generator.render import render


@pytest.fixture(scope="module")
def ds():
    return Dataset.load(DEFAULT_OUT)


@pytest.fixture
def settings(tmp_path):
    return Settings(mode=RunMode.OFFLINE, review_log_path=tmp_path / "reviews.jsonl")


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


@pytest.fixture
def demo(client):
    """The full synthetic dataset as a batch. TestClient runs background tasks before returning."""
    batch = client.post("/batches/demo", json={}).json()
    assert batch["status"] == "queued"
    return batch["id"]


def label_of(ds, code, variant=None):
    return next(l for l in ds.labels if l.code.value == code and (variant is None or l.variant == variant))


def test_health_and_config(client):
    assert client.get("/health").json() == {"status": "ok", "mode": "offline"}
    config = client.get("/config").json()
    assert config["auto_resolvable"] == ["E01", "E04"] and config["auto_approve_confidence"] == 0.95


def test_demo_batch_processes_everything(client, demo):
    summary = client.get(f"/batches/{demo}").json()
    assert summary | {"created_at": None} == summary | {
        "status": "complete", "total": 500, "processed": 500, "failed": 0, "escalated": 135, "pending_review": 135,
        "mode": "offline", "created_at": None}
    assert [b["id"] for b in client.get("/batches").json()] == [demo]


def test_create_batch_from_json(client, ds):
    docs = ds.invoices[:5]
    body = {
        "name": "five",
        "purchase_orders": [p.model_dump(mode="json") for p in ds.purchase_orders],
        "goods_receipts": [g.model_dump(mode="json") for g in ds.goods_receipts],
        "invoices": [{"invoice": d.invoice.model_dump(mode="json")} for d in docs],
    }
    batch = client.post("/batches", json=body).json()
    rows = client.get(f"/batches/{batch['id']}/results").json()
    assert [r["doc_id"] for r in rows] == ["DOC-0001", "DOC-0002", "DOC-0003", "DOC-0004", "DOC-0005"]
    assert [r["code"] for r in rows] == [l.code.value for l in ds.labels[:5]]


def test_invoice_input_needs_exactly_one_form(client, ds):
    body = {"purchase_orders": [], "invoices": [{"doc_id": "X"}]}
    assert client.post("/batches", json=body).status_code == 422
    dup = {"purchase_orders": [], "invoices": [{"doc_id": "X", "document": "a"}, {"doc_id": "X", "document": "b"}]}
    assert client.post("/batches", json=dup).status_code == 422


def test_results_filtering_and_triage_order(client, demo):
    e02 = client.get(f"/batches/{demo}/results", params={"code": "E02", "limit": 1000}).json()
    assert len(e02) == 25 and {r["action"] for r in e02} == {"escalate"}
    queue = client.get(f"/batches/{demo}/results", params={"action": "escalate", "sort": "confidence"}).json()
    assert [r["confidence"] for r in queue] == sorted(r["confidence"] for r in queue)
    assert client.get(f"/batches/{demo}/results", params={"code": "E99"}).status_code == 422


def test_result_detail_and_evidence_links(client, demo, ds):
    label = label_of(ds, "E03", "partial_delivery")
    detail = client.get(f"/batches/{demo}/results/{label.doc_id}").json()
    result = detail["result"]
    assert result["classification"]["code"] == "E03" and result["brief"]["what_i_found"]
    po = result["match"]["matched_po"]["po_number"]
    assert client.get(f"/batches/{demo}/purchase-orders/{po}").json()["po_number"] == po
    assert client.get(f"/batches/{demo}/purchase-orders/{po}/goods-receipt").json()["po_number"] == po
    source = client.get(f"/batches/{demo}/sources/{label.doc_id}")
    assert source.headers["content-type"] == "application/json"
    assert client.get(f"/batches/{demo}/results/DOC-9999").status_code == 404
    assert client.get("/batches/B-missing").status_code == 404


def test_confirming_an_escalation_is_not_an_override(client, demo, ds, settings):
    doc = label_of(ds, "E02").doc_id
    review = client.post(f"/batches/{demo}/results/{doc}/review",
                         json={"decision": "approve", "analyst": "A. Analyst", "note": "Price rise agreed"}).json()
    assert review["is_override"] is False and review["new_code"] == "E02"
    logged = [json.loads(line) for line in settings.review_log_path.read_text().splitlines()]
    assert logged[0]["doc_id"] == doc


def test_override_requires_reason_code(client, demo, ds):
    doc = label_of(ds, "E08", "typo").doc_id
    url = f"/batches/{demo}/results/{doc}/review"
    change = {"decision": "approve", "new_code": "clean", "analyst": "A. Analyst"}
    assert client.post(url, json=change).status_code == 422
    review = client.post(url, json=change | {"reason": "supplier_name_variant_acceptable"}).json()
    assert review["is_override"] and review["original_code"] == "E08"


def test_reversing_an_auto_approval_counts_on_dashboard(client, demo, ds):
    doc = label_of(ds, "clean").doc_id
    client.post(f"/batches/{demo}/results/{doc}/review",
                json={"decision": "reject", "analyst": "A. Analyst", "reason": "other", "note": "fraud flag"})
    d = client.get(f"/batches/{demo}/dashboard").json()
    assert d["overrides"] == 1 and d["reversed_autonomous_decisions"] == 1 and d["override_reasons"] == {"other": 1}


def test_dashboard_metrics(client, demo):
    d = client.get(f"/batches/{demo}/dashboard").json()
    assert d["invoices"] == 500 and d["exceptions"] == 200
    assert d["by_code"]["clean"] == 300 and d["by_action"] == {"auto_approve": 340, "auto_reject": 25, "escalate": 135}
    assert d["auto_resolution_rate"] == pytest.approx(65 / 200)  # E01 (40) + E04 (25) of 200 exceptions
    assert d["straight_through_rate"] == pytest.approx(365 / 500)
    assert d["pending_review"] == 135 and d["override_rate"] == 0
    assert len(d["top_suppliers"]) == 5 and d["llm"]["calls"] == 0


def test_audit_export_json_and_csv(client, demo):
    approved = client.get(f"/batches/{demo}/audit", params={"action": "auto_approve"}).json()
    assert len(approved) == 340 and all(r["confidence"] >= 0.95 and r["rationale"] for r in approved)
    csv_resp = client.get(f"/batches/{demo}/audit", params={"format": "csv"})
    assert csv_resp.headers["content-type"].startswith("text/csv")
    lines = csv_resp.text.strip().splitlines()
    assert lines[0].startswith("batch_id,doc_id") and len(lines) == 501


def test_single_invoice_scoring_is_duplicate_checked_against_batch(client, demo, ds):
    original = next(d for d, l in zip(ds.invoices, ds.labels) if l.code.value == "clean" and l.variant is None)
    detail = client.post(f"/batches/{demo}/invoices", json={"invoice": original.invoice.model_dump(mode="json")})
    assert detail.status_code == 201
    c = detail.json()["result"]["classification"]
    assert (c["code"], c["action"]) == ("E04", "auto_reject")
    assert detail.json()["result"]["doc_id"] == "DOC-0501"


def test_uploaded_document_without_llm_goes_to_manual_entry(client, demo, ds):
    text = render(ds.invoices[0].invoice)
    resp = client.post(f"/batches/{demo}/documents", files={"file": ("inv.txt", text.encode(), "text/plain")})
    result = resp.json()["result"]
    assert resp.status_code == 201 and result["extraction"]["needs_manual_entry"]
    assert result["classification"]["action"] == "escalate" and result["classification"]["code"] is None
    source = client.get(f"/batches/{demo}/sources/{result['doc_id']}")
    assert source.text == text


def test_cannot_add_to_a_batch_still_processing(client, settings, ds):
    batch = client.app.state.registry.create("pending", RunMode.OFFLINE, ds.purchase_orders, ds.goods_receipts, [])
    resp = client.post(f"/batches/{batch.id}/invoices", json={"document": "x"})
    assert resp.status_code == 409


# ---------------------------------------------------------------- policy sandbox


def test_widening_the_autonomy_boundary_shows_what_it_would_settle(client, demo):
    """D-01's open question, made measurable: what does allowing E03 actually change?"""
    sim = client.post(f"/batches/{demo}/simulate", json={"auto_resolvable": ["E01", "E03", "E04"]}).json()
    assert sim["llm"] == "rules"
    assert sim["before"]["by_action"] == {"auto_approve": 340, "auto_reject": 25, "escalate": 135}
    assert sim["after"]["auto_resolution_rate"] > sim["before"]["auto_resolution_rate"]
    assert sim["newly_autonomous"] == len([c for c in sim["changed"] if c["before_action"] == "escalate"])
    assert all(c["before_code"] == "E03" for c in sim["changed"])
    assert any("E03" in note for note in sim["risk"])


def test_loosening_tolerance_moves_invoices_from_e02_to_e01(client, demo):
    sim = client.post(f"/batches/{demo}/simulate",
                      json={"tolerance_pct": "0.2", "tolerance_absolute": "100000"}).json()
    promoted = [c for c in sim["changed"] if c["before_code"] == "E02"]
    assert promoted and all(c["after_code"] == "E01" for c in promoted)
    assert any("approved for payment" in note for note in sim["risk"])

    # Reclassifying is not the same as approving: an invoice with no goods receipt keeps a
    # confidence penalty, so it stays with a human even once the amount is within tolerance.
    approved = [c for c in promoted if c["after_action"] == "auto_approve"]
    held = [c for c in promoted if c["after_action"] == "escalate"]
    assert approved and held
    assert all(c["after_confidence"] >= 0.95 for c in approved)
    assert all(c["after_confidence"] < 0.95 for c in held)


def test_raising_the_approval_bar_sends_work_back_to_analysts(client, demo):
    sim = client.post(f"/batches/{demo}/simulate", json={"auto_approve_confidence": 0.999}).json()
    assert sim["newly_escalated"] > 0 and sim["newly_autonomous"] == 0
    assert sim["after"]["straight_through_rate"] < sim["before"]["straight_through_rate"]
    assert any("back to the review queue" in note for note in sim["risk"])


def test_unchanged_policy_changes_nothing(client, demo):
    sim = client.post(f"/batches/{demo}/simulate", json={}).json()
    assert sim["changed"] == [] and sim["before"] == sim["after"]
    assert sim["risk"] == ["Nothing changes on this batch. The thresholds that moved are not the ones "
                           "binding here."]
