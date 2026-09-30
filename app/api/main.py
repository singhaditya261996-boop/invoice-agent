"""HTTP API wrapping the InvoiceAgent pipeline.

Batches (US-01) are processed in the background; poll GET /batches/{id} for status. Single
invoices (P0 scoring) are processed synchronously against a completed batch's reference data.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api.schemas import (
    AuditRecord,
    BatchCreate,
    BatchSummary,
    DemoBatchCreate,
    InvoiceInput,
    ResultDetail,
    ResultRow,
    ReviewCreate,
)
from app.api.state import Batch, BatchStatus, Registry, Source
from app.config import Settings, load_settings
from app.metrics import Dashboard, summarize
from app.models import (
    Action,
    ConfidenceBand,
    Decision,
    ExceptionCode,
    GoodsReceipt,
    InvoiceResult,
    PurchaseOrder,
    Review,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    registry = Registry(settings)
    app = FastAPI(title="InvoiceAgent", version="0.1.0",
                  description="Agentic AP invoice exception triage. See docs/prd.md.")
    app.state.registry = registry
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def get_batch(batch_id: str) -> Batch:
        batch = registry.batches.get(batch_id)
        if batch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"batch {batch_id} not found")
        return batch

    def get_result(batch: Batch, doc_id: str) -> InvoiceResult:
        if doc_id in batch.results:
            return batch.results[doc_id]
        if doc_id in batch.errors:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{doc_id} failed: {batch.errors[doc_id]}")
        if doc_id in batch.sources:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{doc_id} has not been processed yet")
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"invoice {doc_id} not in batch {batch.id}")

    # ------------------------------------------------------------------ service

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode.value}

    @app.get("/config")
    def config() -> dict:
        """The decision thresholds in force, so the UI can explain the agent's behaviour."""
        s = settings
        return {
            "default_mode": s.mode.value,
            "llm_model": s.llm_model,
            "tolerance": {"pct": str(s.default_tolerance.pct), "absolute_gbp": str(s.default_tolerance.absolute),
                          "rule": "whichever is smaller (D-02)"},
            "auto_approve_confidence": s.auto_approve_confidence,
            "auto_reject_duplicate_confidence": s.auto_reject_duplicate_confidence,
            "auto_resolvable": sorted(c.value for c in s.auto_resolvable),
            "min_match_score": s.min_match_score,
            "confidence_bands": {"green": f"> {s.band_green_min}", "amber": f"{s.band_amber_min}-{s.band_green_min}",
                                 "red": f"< {s.band_amber_min}"},
            "vat_rate": str(s.vat_rate),
            "duplicate_window_days": s.duplicate_date_window_days,
        }

    # ------------------------------------------------------------------ batches

    @app.post("/batches", status_code=status.HTTP_201_CREATED)
    def create_batch(body: BatchCreate, background: BackgroundTasks) -> BatchSummary:
        items = _items(body.invoices)
        batch = registry.create(body.name, body.mode, body.purchase_orders, body.goods_receipts, items)
        background.add_task(batch.run)
        return _summary(batch)

    @app.post("/batches/demo", status_code=status.HTTP_201_CREATED)
    def create_demo_batch(body: DemoBatchCreate, background: BackgroundTasks) -> BatchSummary:
        """Load the synthetic dataset (data/synthetic) as a batch."""
        from data.generator.dataset import Dataset, stratified_sample
        from data.generator.generate import DEFAULT_OUT

        if not (DEFAULT_OUT / "invoices.json").exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no synthetic dataset; run python -m data.generator.generate")
        ds = Dataset.load(DEFAULT_OUT)
        wanted = set(stratified_sample(ds, body.limit))
        docs = [d for d in ds.invoices if d.doc_id in wanted]
        if body.input == "documents":
            items = [(d.doc_id, Source("document", (DEFAULT_OUT / "documents" / f"{d.doc_id}.txt").read_text(),
                                       f"{d.doc_id}.txt")) for d in docs]
        else:
            items = [(d.doc_id, Source("invoice", d.invoice)) for d in docs]
        batch = registry.create(f"Synthetic dataset ({body.input}, {len(items)} invoices)", body.mode,
                                ds.purchase_orders, ds.goods_receipts, items)
        background.add_task(batch.run)
        return _summary(batch)

    @app.get("/batches")
    def list_batches() -> list[BatchSummary]:
        return [_summary(b) for b in sorted(registry.batches.values(), key=lambda b: b.created_at, reverse=True)]

    @app.get("/batches/{batch_id}")
    def get_batch_summary(batch_id: str) -> BatchSummary:
        return _summary(get_batch(batch_id))

    # ------------------------------------------------------------------ single invoice scoring (P0)

    @app.post("/batches/{batch_id}/invoices", status_code=status.HTTP_201_CREATED)
    def score_invoice(batch_id: str, body: InvoiceInput) -> ResultDetail:
        batch = _ready_for_additions(get_batch(batch_id))
        (doc_id, source), = _items([body], start=batch.total + 1, taken=batch.sources.keys())
        return _detail(batch, doc_id, batch.add(doc_id, source))

    @app.post("/batches/{batch_id}/documents", status_code=status.HTTP_201_CREATED)
    async def upload_document(batch_id: str, file: UploadFile = File(...)) -> ResultDetail:
        """Score an uploaded invoice document (PDF or text) via LLM extraction."""
        batch = _ready_for_additions(get_batch(batch_id))
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "document exceeds 10 MB")
        content = data if data.startswith(b"%PDF") else data.decode("utf-8", errors="replace")
        doc_id = _next_doc_id(batch.total + 1, batch.sources.keys())
        return _detail(batch, doc_id, batch.add(doc_id, Source("document", content, file.filename)))

    def _ready_for_additions(batch: Batch) -> Batch:
        if batch.status != BatchStatus.COMPLETE:
            raise HTTPException(status.HTTP_409_CONFLICT, "batch is still processing; add invoices once it completes")
        return batch

    def _detail(batch: Batch, doc_id: str, result: InvoiceResult | None) -> ResultDetail:
        if result is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{doc_id} failed: {batch.errors[doc_id]}")
        return ResultDetail(result=result, review=batch.reviews.get(doc_id))

    # ------------------------------------------------------------------ results (US-02)

    @app.get("/batches/{batch_id}/results")
    def list_results(
        batch_id: str,
        code: ExceptionCode | None = None,
        action: Action | None = None,
        band: ConfidenceBand | None = None,
        reviewed: bool | None = None,
        sort: Literal["order", "confidence"] = "order",
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> list[ResultRow]:
        """Review queue. sort=confidence puts the least certain first (trust design §7.1)."""
        batch = get_batch(batch_id)
        rows = [_row(r, batch.reviews.get(doc_id)) for doc_id, r in list(batch.results.items())]
        rows = [r for r in rows
                if (code is None or r.code == code) and (action is None or r.action == action)
                and (band is None or r.band == band) and (reviewed is None or (r.review is not None) == reviewed)]
        if sort == "confidence":
            rows.sort(key=lambda r: r.confidence)
        return rows[offset: offset + limit]

    @app.get("/batches/{batch_id}/results/{doc_id}")
    def get_result_detail(batch_id: str, doc_id: str) -> ResultDetail:
        batch = get_batch(batch_id)
        return ResultDetail(result=get_result(batch, doc_id), review=batch.reviews.get(doc_id))

    @app.get("/batches/{batch_id}/sources/{doc_id}")
    def get_source(batch_id: str, doc_id: str) -> Response:
        """Evidence link: the invoice as submitted."""
        source = get_batch(batch_id).sources.get(doc_id)
        if source is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"invoice {doc_id} not found")
        if source.kind == "invoice":
            return Response(source.content.model_dump_json(indent=2), media_type="application/json")
        if isinstance(source.content, bytes):
            return Response(source.content, media_type="application/pdf")
        return Response(source.content, media_type="text/plain; charset=utf-8")

    @app.get("/batches/{batch_id}/purchase-orders/{po_number}")
    def get_purchase_order(batch_id: str, po_number: str) -> PurchaseOrder:
        po = get_batch(batch_id).agent.store.pos.get(po_number)
        if po is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"PO {po_number} not found")
        return po

    @app.get("/batches/{batch_id}/purchase-orders/{po_number}/goods-receipt")
    def get_goods_receipt(batch_id: str, po_number: str) -> GoodsReceipt:
        gr = get_batch(batch_id).agent.store.goods_receipts.get(po_number)
        if gr is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no goods receipt for PO {po_number}")
        return gr

    # ------------------------------------------------------------------ analyst review (US-03)

    @app.post("/batches/{batch_id}/results/{doc_id}/review", status_code=status.HTTP_201_CREATED)
    def review_result(batch_id: str, doc_id: str, body: ReviewCreate) -> Review:
        batch = get_batch(batch_id)
        c = get_result(batch, doc_id).classification
        new_code = body.new_code if body.new_code is not None else c.code
        is_override = (c.code is not None and new_code != c.code) or \
            (c.action == Action.AUTO_APPROVE and body.decision != Decision.APPROVE) or \
            (c.action == Action.AUTO_REJECT and body.decision != Decision.REJECT)
        if is_override and body.reason is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "a reason code is required when overriding the agent (D-05)")
        review = Review(
            doc_id=doc_id, invoice_number=batch.results[doc_id].invoice_number, original_code=c.code,
            original_action=c.action, new_code=new_code, decision=body.decision, is_override=is_override,
            reason=body.reason, note=body.note, analyst=body.analyst, created_at=datetime.now(timezone.utc),
        )
        registry.record_review(batch, review)
        return review

    # ------------------------------------------------------------------ dashboard (US-04) and audit (US-05)

    @app.get("/batches/{batch_id}/dashboard")
    def dashboard(batch_id: str) -> Dashboard:
        batch = get_batch(batch_id)
        return summarize(list(batch.results.values()), batch.reviews, batch.agent.settings)

    @app.get("/batches/{batch_id}/audit", response_model=None)
    def audit(batch_id: str, format: Literal["json", "csv"] = "json",
              action: Action | None = None) -> list[AuditRecord] | Response:
        batch = get_batch(batch_id)
        records = [_audit_record(batch, doc_id, r) for doc_id, r in batch.results.items()
                   if action is None or r.classification.action == action]
        if format == "json":
            return records
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(AuditRecord.model_fields))
        writer.writeheader()
        writer.writerows(r.model_dump(mode="json") for r in records)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="audit-{batch.id}.csv"'})

    return app


# ---------------------------------------------------------------------- helpers


def _next_doc_id(n: int, taken) -> str:
    while f"DOC-{n:04d}" in taken:
        n += 1
    return f"DOC-{n:04d}"


def _items(inputs: list[InvoiceInput], start: int = 1, taken=()) -> list[tuple[str, Source]]:
    items: list[tuple[str, Source]] = []
    seen = set(taken)
    for i, inp in enumerate(inputs, start):
        doc_id = inp.doc_id or _next_doc_id(i, seen)
        if doc_id in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"duplicate doc_id {doc_id}")
        seen.add(doc_id)
        items.append((doc_id, Source("invoice", inp.invoice) if inp.invoice else Source("document", inp.document)))
    return items


def _summary(batch: Batch) -> BatchSummary:
    results = list(batch.results.values())
    escalated = [r for r in results if r.classification.action == Action.ESCALATE]
    return BatchSummary(
        id=batch.id, name=batch.name, mode=batch.mode, status=batch.status.value, created_at=batch.created_at,
        total=batch.total, processed=len(results), failed=len(batch.errors), escalated=len(escalated),
        pending_review=sum(r.doc_id not in batch.reviews for r in escalated),
    )


def _row(r: InvoiceResult, review: Review | None) -> ResultRow:
    inv = r.extraction.invoice
    po = r.match.matched_po if r.match else None
    c = r.classification
    return ResultRow(
        doc_id=r.doc_id, invoice_number=r.invoice_number,
        supplier_name=inv.supplier_name if inv else None, total_amount=inv.total_amount if inv else None,
        po_number=po.po_number if po else None, match_method=r.match.method if r.match else None,
        code=c.code, action=c.action, confidence=c.confidence, band=c.band,
        summary=r.brief.summary if r.brief else c.rationale,
        review=review.decision if review else None, is_override=bool(review and review.is_override),
    )


def _audit_record(batch: Batch, doc_id: str, r: InvoiceResult) -> AuditRecord:
    inv = r.extraction.invoice
    c = r.classification
    review = batch.reviews.get(doc_id)
    return AuditRecord(
        batch_id=batch.id, doc_id=doc_id, invoice_number=r.invoice_number,
        supplier_name=inv.supplier_name if inv else None, total_amount=str(inv.total_amount) if inv else None,
        processed_at=r.processed_at, mode=r.mode,
        po_number=r.match.matched_po.po_number if r.match and r.match.matched_po else None,
        match_method=r.match.method if r.match else None, match_score=r.match.score if r.match else None,
        code=c.code.value if c.code else None, action=c.action.value, confidence=c.confidence, band=c.band.value,
        rationale=c.rationale,
        discrepancies=" | ".join(d.detail for d in r.validation.discrepancies) if r.validation else "",
        llm_calls=len(r.llm_calls),
        review_decision=review.decision.value if review else None, reviewed_by=review.analyst if review else None,
        review_reason=review.reason.value if review and review.reason else None,
        is_override=bool(review and review.is_override),
    )


app = create_app()
