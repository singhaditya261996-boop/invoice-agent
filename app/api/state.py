"""In-memory batch registry. MVP scope: batches live for the lifetime of the process; analyst
reviews are also appended to a JSONL log so the feedback-loop data (D-05) survives restarts."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.agent.llm import make_llm
from app.agent.pipeline import InvoiceAgent
from app.agent.tools import DataStore
from app.config import RunMode, Settings
from app.models import GoodsReceipt, Invoice, InvoiceResult, PurchaseOrder, Review

Raw = Invoice | str | bytes


class BatchStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"


@dataclass
class Source:
    kind: str  # "invoice" | "document"
    content: Raw
    filename: str | None = None


@dataclass
class Batch:
    id: str
    name: str
    mode: RunMode
    created_at: datetime
    agent: InvoiceAgent
    pending: list[tuple[str, Source]]
    sources: dict[str, Source] = field(default_factory=dict)
    results: dict[str, InvoiceResult] = field(default_factory=dict)  # insertion = processing order
    reviews: dict[str, Review] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    status: BatchStatus = BatchStatus.QUEUED
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def total(self) -> int:
        return len(self.sources)

    def run(self) -> None:
        """Process queued invoices in order (so each is duplicate-checked against earlier ones)."""
        self.status = BatchStatus.PROCESSING
        while self.pending:
            doc_id, source = self.pending.pop(0)
            self._process(doc_id, source)
        self.status = BatchStatus.COMPLETE

    def add(self, doc_id: str, source: Source) -> InvoiceResult | None:
        self.sources[doc_id] = source
        return self._process(doc_id, source)

    def _process(self, doc_id: str, source: Source) -> InvoiceResult | None:
        with self.lock:
            try:
                result = self.agent.process(source.content, doc_id)
            except Exception as e:  # one bad invoice must not stop the batch
                self.errors[doc_id] = f"{type(e).__name__}: {e}"
                return None
            self.results[doc_id] = result
            return result


class Registry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.batches: dict[str, Batch] = {}
        self._log_lock = threading.Lock()

    def create(
        self,
        name: str | None,
        mode: RunMode | None,
        purchase_orders: list[PurchaseOrder],
        goods_receipts: list[GoodsReceipt],
        items: list[tuple[str, Source]],
    ) -> Batch:
        settings = self.settings.model_copy(update={"mode": mode or self.settings.mode})
        batch_id = f"B-{uuid.uuid4().hex[:8]}"
        agent = InvoiceAgent(DataStore(purchase_orders, goods_receipts), settings, make_llm(settings))
        batch = Batch(
            id=batch_id, name=name or batch_id, mode=settings.mode, created_at=datetime.now(timezone.utc),
            agent=agent, pending=list(items), sources=dict(items),
        )
        self.batches[batch_id] = batch
        return batch

    def record_review(self, batch: Batch, review: Review) -> None:
        batch.reviews[review.doc_id] = review
        path = self.settings.review_log_path
        with self._log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(review.model_dump_json() + "\n")
