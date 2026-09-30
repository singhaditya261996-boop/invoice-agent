import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent.classifier import classify
from app.agent.extractor import extract_invoice_fields
from app.agent.llm import ClaudeLLM, FixtureStore, GeminiLLM, ReplayLLM, to_google_schema
from app.agent.normalize import canonical_po_ref, supplier_key
from app.agent.pipeline import InvoiceAgent
from app.agent.tools import DataStore
from app.agent.validator import read_gr_notes
from app.config import RunMode, Settings, ToleranceConfig
from app.models import (
    Action,
    Discrepancy,
    ExceptionCode as EC,
    ExtractionResult,
    LLMCall,
    MatchResult,
    ValidationResult,
)
from data.generator.dataset import Dataset
from data.generator.generate import DEFAULT_OUT
from data.generator.render import render

OFFLINE = Settings(mode=RunMode.OFFLINE)


class FakeLLM:
    def __init__(self, **responses):
        self.responses = responses
        self.calls: list[LLMCall] = []
        self.requests: list[tuple[str, object]] = []

    def json(self, task, system, content, schema):
        self.calls.append(LLMCall(step=task, model="fake"))
        self.requests.append((task, content))
        return self.responses.get(task)


@pytest.fixture(scope="module")
def ds():
    return Dataset.load(DEFAULT_OUT)


def run(ds, docs, settings=OFFLINE, llm=None):
    agent = InvoiceAgent(DataStore(ds.purchase_orders, ds.goods_receipts), settings, llm)
    return agent.process_batch(docs)


# ---------------------------------------------------------------- end to end (rules only)


def test_offline_pipeline_matches_ground_truth(ds):
    results = run(ds, [(d.doc_id, d.invoice.model_dump(mode="json")) for d in ds.invoices])
    for r, label in zip(results, ds.labels):
        got_po = r.match.matched_po.po_number if r.match.matched_po else None
        assert (r.classification.code, r.classification.action, got_po) == \
            (label.code, label.action, label.true_po_number), label.doc_id


def test_never_auto_approves_a_problem_invoice(ds):
    """The critical failure mode (PRD §6): holds even if other metrics regress."""
    results = run(ds, [(d.doc_id, d.invoice) for d in ds.invoices])
    for r, label in zip(results, ds.labels):
        if r.classification.action == Action.AUTO_APPROVE:
            assert label.code in (EC.CLEAN, EC.E01), label.doc_id
        else:
            assert r.brief is not None


def test_audit_record_is_complete(ds):
    r = run(ds, [(ds.invoices[0].doc_id, ds.invoices[0].invoice)])[0]
    assert r.doc_id == ds.invoices[0].doc_id and r.extraction.method == "structured"
    assert r.validation.checks_performed and r.classification.rationale and r.llm_calls == []


# ---------------------------------------------------------------- normalisation


@pytest.mark.parametrize("ref,expected", [
    ("PO2026004817", "PO-2026-004817"), ("po-2026-004817", "PO-2026-004817"), ("PO 2026 004817", "PO-2026-004817"),
    ("PO#2026-004817", "PO-2026-004817"), ("PO/2026/004817", "PO-2026-004817"),
    ("PO-2026-0048", "PO-2026-0048"), ("PO-2026-04817", "PO-2026-04817"), ("", None), (None, None),
])
def test_canonical_po_ref(ref, expected):
    assert canonical_po_ref(ref) == expected


def test_supplier_key_ignores_formatting_only():
    base = supplier_key("Harrowgate Stationery Co Ltd")
    for variant in ("Harrowgate Stationery Company Limited", "HARROWGATE STATIONERY CO LTD", "Harrowgate Stationery Co."):
        assert supplier_key(variant) == base
    assert supplier_key("Marlow and Finch Legal Services") == supplier_key("Marlow & Finch Legal Services LLP")
    assert supplier_key("Harrowgate Stationery Co (Yorkshire) Ltd") != base


def test_supplier_tolerance_override_changes_outcome(ds):
    doc, label = next((d, l) for d, l in zip(ds.invoices, ds.labels) if l.code == EC.E01)
    po = next(p for p in ds.purchase_orders if p.po_number == label.true_po_number)
    strict = Settings(mode=RunMode.OFFLINE, supplier_tolerances={po.supplier_id: ToleranceConfig(absolute=Decimal("0"))})
    assert run(ds, [(doc.doc_id, doc.invoice)], strict)[0].classification.code == EC.E02


# ---------------------------------------------------------------- LLM steps


def test_gr_notes_llm_overrides_keyword_false_positive():
    note = "Nothing missing, all boxes checked"
    assert read_gr_notes(note, None).indicates_shortfall  # keyword rules are fooled
    llm = FakeLLM(gr_notes={"indicates_shortfall": False, "units_not_received": None, "explanation": "full delivery"})
    reading = read_gr_notes(note, llm)
    assert not reading.indicates_shortfall and reading.used_llm


def test_gr_notes_falls_back_when_llm_unavailable():
    reading = read_gr_notes("Box 3 damaged, returned 5 units", FakeLLM())
    assert reading.indicates_shortfall and reading.units == 5 and not reading.used_llm


def _validation(*codes_conf):
    return ValidationResult(discrepancies=[
        Discrepancy(check="x", field="f", detail=f"{c.value} finding", suggested_code=c, confidence=conf)
        for c, conf in codes_conf
    ])


def test_overlapping_discrepancies_use_llm_but_rules_decide_action():
    extraction = ExtractionResult(invoice=None, confidence=1.0)
    match = MatchResult(matched_po=None, method="none", score=0.0)
    validation = _validation((EC.E01, 0.99), (EC.E07, 0.96))
    llm = FakeLLM(classify={"root_cause": "E01", "explanation": "rounding explains both"})
    c = classify(extraction, match, validation, OFFLINE, llm)
    assert c.code == EC.E01 and c.used_llm
    assert c.action == Action.ESCALATE  # overlap penalty keeps it below the 95% auto-approve bar


def test_llm_root_cause_outside_findings_is_ignored():
    extraction = ExtractionResult(invoice=None, confidence=1.0)
    match = MatchResult(matched_po=None, method="none", score=0.0)
    llm = FakeLLM(classify={"root_cause": "E01", "explanation": "not a finding"})
    c = classify(extraction, match, _validation((EC.E02, 0.97), (EC.E08, 0.95)), OFFLINE, llm)
    assert c.code == EC.E08 and not c.used_llm  # rule precedence: E08 before E02


def test_brief_narrative_from_llm_keeps_template_facts(ds):
    doc, label = next((d, l) for d, l in zip(ds.invoices, ds.labels) if l.code == EC.E02)
    narrative = {"summary": "S", "what_i_could_not_resolve": "U", "recommended_action": "R"}
    r = run(ds, [(doc.doc_id, doc.invoice)], llm=FakeLLM(brief=narrative))[0]
    assert (r.brief.summary, r.brief.what_i_could_not_resolve, r.brief.recommended_action) == ("S", "U", "R")
    assert any("PO total" in f for f in r.brief.what_i_found)
    assert r.llm_calls[-1].step == "brief"
    assert {c.step for c in r.llm_calls} <= {"gr_notes", "brief"}  # no LLM for single-cause classification


# ---------------------------------------------------------------- extraction


def _as_llm_output(invoice, confidence=0.98):
    data = invoice.model_dump(mode="json")
    data.update(unreadable_fields=[], confidence=confidence)
    return data


def test_extract_from_document_text(ds):
    inv = ds.invoices[0].invoice
    llm = FakeLLM(extract=_as_llm_output(inv))
    result = extract_invoice_fields(render(inv), OFFLINE, llm)
    assert result.invoice == inv and not result.needs_manual_entry and result.method == "llm"
    assert inv.invoice_number in llm.requests[0][1]


def test_misread_amount_triggers_manual_entry(ds):
    inv = ds.invoices[0].invoice
    misread = _as_llm_output(inv)
    misread["subtotal"] = str(inv.subtotal * 10)  # the "£12,450 read as £124,500" failure mode
    result = extract_invoice_fields(render(inv), OFFLINE, FakeLLM(extract=misread))
    assert result.needs_manual_entry and result.issues


def test_low_confidence_extraction_escalates_without_classifying(ds):
    inv = ds.invoices[0].invoice
    misread = _as_llm_output(inv)
    misread["total_amount"] = str(inv.total_amount + 100)
    agent = InvoiceAgent(DataStore(ds.purchase_orders, ds.goods_receipts), OFFLINE, FakeLLM(extract=misread))
    r = agent.process(render(inv), "DOC-X")
    assert r.classification.code is None and r.classification.action == Action.ESCALATE and r.match is None
    assert "Subtotal + VAT does not equal the total" in r.brief.what_i_found
    assert r.brief.summary.startswith(f"Invoice {inv.invoice_number}")
    assert [p.verified for p in agent.store.processed] == [False]


def test_resubmission_of_invoice_awaiting_manual_entry_is_not_approved(ds):
    """Found by the simulated-extraction-error eval: a clean resubmission of a misread original was paid twice."""
    doc, label = next((d, l) for d, l in zip(ds.invoices, ds.labels) if l.code == EC.CLEAN and l.variant is None)
    misread = _as_llm_output(doc.invoice)
    misread["total_amount"] = str(doc.invoice.total_amount * 10)

    class Sequence(FakeLLM):
        answers = [misread, _as_llm_output(doc.invoice)]

        def json(self, task, system, content, schema):
            super().json(task, system, content, schema)
            return self.answers.pop(0) if task == "extract" else None

    agent = InvoiceAgent(DataStore(ds.purchase_orders, ds.goods_receipts), OFFLINE, Sequence())
    first = agent.process(render(doc.invoice), "ORIGINAL")
    again = agent.process(render(doc.invoice), "RESUBMITTED")
    assert first.extraction.needs_manual_entry
    assert (again.classification.code, again.classification.action) == (EC.E04, Action.ESCALATE)
    assert "awaiting manual data entry" in again.brief.what_i_found[0]


def test_document_without_llm_escalates_for_manual_entry(ds):
    agent = InvoiceAgent(DataStore(ds.purchase_orders, ds.goods_receipts), OFFLINE, None)
    r = agent.process(render(ds.invoices[0].invoice), "DOC-X")
    assert r.classification.code is None and r.classification.action == Action.ESCALATE
    assert r.brief.recommended_action.startswith("Key the invoice manually")
    assert agent.store.processed == []


def test_invalid_structured_invoice_is_not_processed():
    result = extract_invoice_fields({"invoice_number": "X"}, OFFLINE)
    assert result.needs_manual_entry and "subtotal" in result.missing_fields


# ---------------------------------------------------------------- LLM clients


def test_replay_serves_fixtures_and_reports_misses(tmp_path):
    s = Settings(mode=RunMode.DEMO, fixtures_path=tmp_path / "f.json")
    FixtureStore(s.fixtures_path).put(FixtureStore.key("t", s.llm_model, "sys", "hi", {}), "t", {"ok": True})
    llm = ReplayLLM(s)
    assert llm.json("t", "sys", "hi", {}) == {"ok": True}
    assert llm.json("t", "sys", "other", {}) is None and llm.calls[-1].error == "no_fixture"


def _fake_client(stop_reason="end_turn", text='{"a": 1}'):
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(model=kwargs["model"], stop_reason=stop_reason,
                               content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))), sent


def test_claude_llm_request_shape_and_recording(tmp_path):
    s = Settings(mode=RunMode.LIVE, record_fixtures=True, fixtures_path=tmp_path / "f.json")
    client, sent = _fake_client()
    llm = ClaudeLLM(s, client=client)
    assert llm.json("t", "sys", "hi", {"type": "object"}) == {"a": 1}
    assert sent["model"] == "claude-opus-5" and sent["fallbacks"] == "default"
    assert sent["betas"] == ["server-side-fallback-2026-07-01"]
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": {"type": "object"}}
    assert llm.calls[0].input_tokens == 10
    assert ReplayLLM(Settings(mode=RunMode.DEMO, fixtures_path=s.fixtures_path)).json(
        "t", "sys", "hi", {"type": "object"}) == {"a": 1}


def test_claude_llm_refusal_falls_back():
    client, _ = _fake_client(stop_reason="refusal", text="")
    llm = ClaudeLLM(Settings(mode=RunMode.LIVE), client=client)
    assert llm.json("t", "sys", "hi", {}) is None and llm.calls[0].error == "stop_reason=refusal"


# ---------------------------------------------------------------- alternative provider (Gemini)


def test_google_schema_translation():
    """Google's schema dialect has no additionalProperties, and nullability is a flag."""
    translated = to_google_schema({
        "type": "object",
        "properties": {
            "po_reference": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "lines": {"type": "array", "items": {"type": "object", "properties": {"n": {"type": "string"}},
                                                 "additionalProperties": False}},
        },
        "required": ["po_reference"],
        "additionalProperties": False,
    })
    assert "additionalProperties" not in json.dumps(translated)
    assert translated["properties"]["po_reference"] == {"type": "string", "nullable": True}
    assert translated["required"] == ["po_reference"]


def _fake_google(text='{"a": 1}', error: Exception | None = None):
    sent = {}

    def generate_content(**kwargs):
        sent.update(kwargs)
        if error:
            raise error
        return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
            prompt_token_count=11, candidates_token_count=4, thoughts_token_count=3))

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)), sent


def test_gemini_request_shape_and_token_accounting():
    client, sent = _fake_google()
    llm = GeminiLLM(Settings(mode=RunMode.LIVE, llm_provider="google"), client=client)
    assert llm.json("extract", "sys", "doc text", {"type": "object", "additionalProperties": False}) == {"a": 1}
    assert sent["model"] == "gemini-2.5-flash" and sent["contents"] == ["doc text"]
    assert sent["config"]["response_mime_type"] == "application/json"
    assert sent["config"]["system_instruction"] == "sys"
    assert llm.calls[0].input_tokens == 11 and llm.calls[0].output_tokens == 7  # thinking tokens count as output


def test_gemini_failure_falls_back_to_rules():
    client, _ = _fake_google(error=RuntimeError("400 INVALID_ARGUMENT"))
    llm = GeminiLLM(Settings(mode=RunMode.LIVE, llm_provider="google"), client=client)
    assert llm.json("extract", "sys", "doc", {}) is None
    assert "INVALID_ARGUMENT" in llm.calls[0].error


def test_reuse_recorded_replays_instead_of_calling(tmp_path):
    """A repeat live run must not pay twice for an identical request (quota and cost control)."""
    s = Settings(mode=RunMode.LIVE, record_fixtures=True, reuse_recorded=True, fixtures_path=tmp_path / "f.json")
    client, sent = _fake_client(text='{"a": 1}')
    first = ClaudeLLM(s, client=client)
    assert first.json("t", "sys", "hi", {}) == {"a": 1} and not first.calls[0].cached

    second = ClaudeLLM(s, client=_fake_client(text='{"a": 2}')[0])
    assert second.json("t", "sys", "hi", {}) == {"a": 1}  # replayed, not the new client's answer
    assert second.calls[0].cached
    assert second.json("t", "sys", "different", {}) == {"a": 2}  # a new request still goes out
