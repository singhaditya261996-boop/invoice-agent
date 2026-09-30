"""On-disk dataset format shared by the generator, the API, and the evaluation runner."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.classifier import apply_autonomy_rules
from app.config import Settings
from app.models import Action, ExceptionCode, GoodsReceipt, Invoice, PurchaseOrder

FILES = {
    "purchase_orders": "purchase_orders.json",
    "goods_receipts": "goods_receipts.json",
    "invoices": "invoices.json",
    "labels": "ground_truth.json",
}
MANIFEST = "manifest.json"


class InvoiceDoc(BaseModel):
    """An invoice in batch processing order. doc_id is stable; invoice_number may repeat (duplicates)."""

    doc_id: str
    invoice: Invoice


class GroundTruth(BaseModel):
    doc_id: str
    invoice_number: str
    code: ExceptionCode
    action: Action
    true_po_number: str | None  # None = no PO exists (correct answer is 'no match')
    duplicate_of: str | None = None  # doc_id of the original, for E04
    variant: str | None = None  # generator sub-scenario, e.g. "maverick", "wrong_rate"
    edge_cases: list[str] = Field(default_factory=list)  # deliberately ambiguous cases (PRD §5.1)
    notes: str = ""


class Dataset(BaseModel):
    purchase_orders: list[PurchaseOrder]
    goods_receipts: list[GoodsReceipt]
    invoices: list[InvoiceDoc]
    labels: list[GroundTruth]

    def write(self, out_dir: Path, manifest: dict) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for attr, filename in FILES.items():
            rows = [m.model_dump(mode="json") for m in getattr(self, attr)]
            (out_dir / filename).write_text(json.dumps(rows, indent=2) + "\n")
        (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")

    @classmethod
    def load(cls, data_dir: Path) -> Dataset:
        return cls(**{attr: json.loads((data_dir / f).read_text()) for attr, f in FILES.items()})


def expected_action(code: ExceptionCode, settings: Settings) -> Action:
    """Ground-truth action: what the autonomy rules (D-01, D-06) require with a fully confident classification."""
    return apply_autonomy_rules(code, 1.0, settings)


def stratified_sample(ds: Dataset, limit: int | None) -> list[str]:
    """Doc ids for all invoices, or a sample of `limit` covering every (code, variant) round-robin.

    Originals of sampled duplicates are always included, so each E04 label stays satisfiable.
    Returned in processing order.
    """
    order = [d.doc_id for d in ds.invoices]
    if not limit or limit >= len(order):
        return order
    groups: dict[tuple, list[str]] = defaultdict(list)
    for l in ds.labels:
        groups[(l.code.value, l.variant or "")].append(l.doc_id)
    queues = [groups[k][:] for k in sorted(groups)]
    picked: set[str] = set()
    while len(picked) < limit and any(queues):
        for q in queues:
            if q and len(picked) < limit:
                picked.add(q.pop(0))
    labels = {l.doc_id: l for l in ds.labels}
    picked |= {labels[d].duplicate_of for d in picked if labels[d].duplicate_of}
    return [d for d in order if d in picked]
