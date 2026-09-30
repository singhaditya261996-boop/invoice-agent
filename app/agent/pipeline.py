"""Orchestration: runs extract -> match -> validate -> classify -> report sequentially.

Sequential by design: each step consumes the previous step's output (PRD §3.1). Every
invoice yields an InvoiceResult, which is also its audit-trail record (US-05).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.agent.classifier import Calibrator, classify, confidence_band
from app.agent.extractor import extract_invoice_fields
from app.agent.llm import LLM, make_llm
from app.agent.matcher import match_invoice
from app.agent.reporter import generate_escalation_brief
from app.agent.tools import DataStore
from app.agent.validator import validate
from app.config import Settings
from app.models import Action, Classification, Invoice, InvoiceResult


class InvoiceAgent:
    def __init__(self, store: DataStore, settings: Settings, llm: LLM | None = None,
                 calibrator: Calibrator | None = None) -> None:
        self.store = store
        self.settings = settings
        self.llm = llm
        self.calibrator = calibrator or Calibrator.load()

    @classmethod
    def from_settings(cls, store: DataStore, settings: Settings) -> InvoiceAgent:
        return cls(store, settings, make_llm(settings))

    def process(self, raw: Invoice | dict | str | bytes, doc_id: str | None = None) -> InvoiceResult:
        start = time.monotonic()
        first_call = len(self.llm.calls) if self.llm else 0
        s, llm = self.settings, self.llm

        extraction = extract_invoice_fields(raw, s, llm)
        invoice = extraction.invoice
        match = validation = None
        if extraction.needs_manual_entry or invoice is None:
            classification = Classification(
                code=None, confidence=extraction.confidence, band=confidence_band(extraction.confidence, s),
                action=Action.ESCALATE,
                rationale="Extraction confidence below threshold; flagged for manual data entry.",
            )
        else:
            match = match_invoice(invoice, self.store, s)
            validation = validate(invoice, match, self.store, s, llm)
            classification = classify(extraction, match, validation, s, llm, self.calibrator)
        brief = generate_escalation_brief(invoice, extraction, match, validation, classification, s, llm)

        if invoice is not None:  # misread invoices are still received: later duplicates must find them
            self.store.record(doc_id, invoice, match.matched_po if match else None, verified=match is not None)

        return InvoiceResult(
            doc_id=doc_id,
            invoice_number=invoice.invoice_number if invoice else None,
            processed_at=datetime.now(timezone.utc),
            mode=s.mode.value,
            extraction=extraction,
            match=match,
            validation=validation,
            classification=classification,
            brief=brief,
            llm_calls=self.llm.calls[first_call:] if self.llm else [],
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    def process_batch(self, items: list[tuple[str | None, Invoice | dict | str | bytes]]) -> list[InvoiceResult]:
        """US-01. In order, so each invoice is duplicate-checked against those before it."""
        return [self.process(raw, doc_id) for doc_id, raw in items]


def process_invoice(raw, store: DataStore, settings: Settings, llm: LLM | None = None,
                    doc_id: str | None = None) -> InvoiceResult:
    return InvoiceAgent(store, settings, llm).process(raw, doc_id)


def process_batch(items, store: DataStore, settings: Settings, llm: LLM | None = None) -> list[InvoiceResult]:
    return InvoiceAgent(store, settings, llm).process_batch(items)
