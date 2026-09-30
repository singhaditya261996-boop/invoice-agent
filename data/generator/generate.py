"""Synthetic data generator (PRD §2.3).

Produces a labelled batch of 500 invoices plus the POs and goods receipts they are
matched against, written to data/synthetic/. Output is deterministic for a given seed.

    python -m data.generator.generate [--seed 42] [--out data/synthetic]

Design notes and deviations from the PRD: data/generator/README.md.
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.config import Settings
from app.models import (
    ExceptionCode,
    GoodsReceipt,
    GRLineItem,
    Invoice,
    InvoiceLineItem,
    POLineItem,
    POStatus,
    PurchaseOrder,
)
from data.generator.catalog import (
    APPROVERS,
    BENIGN_GR_NOTES,
    COST_CENTRES,
    NOTES_ONLY_GR_NOTES,
    RECEIVERS,
    SHORTFALL_GR_NOTES,
    SUPPLIERS,
    Supplier,
)
from data.generator.dataset import Dataset, GroundTruth, InvoiceDoc, expected_action
from data.generator.render import write_documents

GENERATOR_VERSION = "1.0"
DEFAULT_SEED = 42
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "synthetic"

# Target invoice distribution by scenario (PRD §2.3; must sum to 500).
DISTRIBUTION = {
    "clean": 300,
    "E01": 40,
    "E02": 25,
    "E03": 30,
    "E04": 25,
    "E05": 30,
    "E06": 15,
    "E07": 20,
    "E08": 15,
}

# Sub-scenario mix within each bucket. Edge cases are deliberately ambiguous (PRD §5.1).
CLEAN_RECURRING_PAIRS = 5  # legitimate same-amount monthly invoices: duplicate false-positive trap
CLEAN_BENIGN_NAME = 25  # "Ltd" vs "Limited" etc.: must NOT be classified E08
CLEAN_PO_FORMAT = 10  # "PO2026004817" for "PO-2026-004817": same PO, different formatting
E02_NO_GR = 10  # no goods receipt on file
E03_NOTES_ONLY = 5  # shortfall described only in GR free-text notes
E05_MISSING, E05_CORRUPTED, E05_MAVERICK = 8, 12, 10
E05_DECOYS = 6  # E05 invoices whose true PO has a near-identical competing PO
E07_WRONG_RATE = 10  # remainder are header-level tax miscalculations
E08_KINDS = ("initialism", "subsidiary", "parent", "trading_name", "typo")
UNBILLED_POS = 30  # open POs with no invoice: realistic noise for fuzzy matching

PENNY = Decimal("0.01")
YEAR_START = date(2026, 1, 5)
ORDER_WINDOW = (YEAR_START, date(2026, 6, 30))
MAX_PO_TOTAL = Decimal("150000")
E01_MAX_PO_TOTAL = Decimal("40000")  # above ~£45k, 0.1% variance already exceeds the £50 tolerance

Line = tuple[str, Decimal, Decimal]  # description, quantity, unit price


def money(x: Decimal | int | str) -> Decimal:
    return Decimal(x).quantize(PENNY, rounding=ROUND_HALF_UP)


def legal_stem(name: str) -> str:
    for suffix in (" Ltd", " plc", " LLP"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


@dataclass(eq=False)
class _Record:
    invoice: Invoice
    supplier: Supplier
    code: ExceptionCode
    true_po: str | None
    variant: str | None = None
    edge_cases: list[str] = field(default_factory=list)
    notes: str = ""
    duplicate_of: _Record | None = None
    doc_id: str = ""


class Generator:
    def __init__(self, seed: int = DEFAULT_SEED, settings: Settings | None = None) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.settings = settings or Settings()
        self.pos: dict[str, PurchaseOrder] = {}
        self.grs: list[GoodsReceipt] = []
        self.records: list[_Record] = []
        self._used_refs: set[str] = set()  # PO/GR numbers plus reserved corrupted refs

    # ------------------------------------------------------------------ primitives

    def _date_between(self, start: date, end: date) -> date:
        return start + timedelta(days=self.rng.randint(0, (end - start).days))

    def _unique_ref(self, prefix: str) -> str:
        while True:
            ref = f"{prefix}-2026-{self.rng.randint(1000, 999999):06d}"
            if ref not in self._used_refs:
                self._used_refs.add(ref)
                return ref

    def _lines(self, supplier: Supplier) -> list[Line]:
        items = self.rng.sample(supplier.items, self.rng.randint(1, min(4, len(supplier.items))))
        return [
            (it.description, Decimal(self.rng.randint(*it.qty)), money(str(self.rng.uniform(*it.price))))
            for it in items
        ]

    def _lines_where(self, supplier: Supplier, ok, max_total: Decimal = MAX_PO_TOTAL) -> list[Line]:
        for _ in range(500):
            lines = self._lines(supplier)
            if lines_total(lines) <= max_total and ok(lines):
                return lines
        raise RuntimeError(f"could not generate acceptable lines for {supplier.name}")

    def make_po(
        self,
        supplier: Supplier,
        lines: list[Line] | None = None,
        *,
        order_window: tuple[date, date] = ORDER_WINDOW,
        order_date: date | None = None,
        lead_days: int | None = None,
        status: POStatus = POStatus.OPEN,
    ) -> PurchaseOrder:
        lines = lines or self._lines_where(supplier, lambda _: True)
        od = order_date or self._date_between(*order_window)
        po_lines = [POLineItem(description=d, quantity=q, unit_price=p, total=money(q * p)) for d, q, p in lines]
        po = PurchaseOrder(
            po_number=self._unique_ref("PO"),
            supplier_name=supplier.name,
            supplier_id=supplier.supplier_id,
            order_date=od,
            delivery_date=od + timedelta(days=self.rng.randint(5, 30) if lead_days is None else lead_days),
            line_items=po_lines,
            total_amount=sum((l.total for l in po_lines), Decimal("0")),
            currency="GBP",
            cost_centre=self.rng.choice(COST_CENTRES),
            approver=self.rng.choice(APPROVERS),
            payment_terms=supplier.payment_terms,
            status=status,
        )
        self.pos[po.po_number] = po
        return po

    def make_gr(
        self,
        po: PurchaseOrder,
        shortfall: dict[int, int] | None = None,
        notes: str | None = None,
        receipt_offset: int | None = None,
    ) -> GoodsReceipt:
        shortfall = shortfall or {}
        offset = self.rng.randint(-2, 5) if receipt_offset is None else receipt_offset
        gr = GoodsReceipt(
            gr_number=self._unique_ref("GR"),
            po_number=po.po_number,
            receipt_date=po.delivery_date + timedelta(days=offset),
            line_items=[
                GRLineItem(description=l.description, quantity_received=l.quantity - shortfall.get(i, 0))
                for i, l in enumerate(po.line_items)
            ],
            receiver=self.rng.choice(RECEIVERS),
            notes=self.rng.choice(BENIGN_GR_NOTES) if notes is None else notes,
        )
        self.grs.append(gr)
        return gr

    def build_invoice(
        self,
        supplier: Supplier,
        lines: list[Line],
        invoice_date: date,
        *,
        po_ref: str | None,
        name: str | None = None,
        vat_rate: Decimal | None = None,
    ) -> Invoice:
        rate = self.settings.vat_rate if vat_rate is None else vat_rate
        inv_lines = []
        for d, q, p in lines:
            net = money(q * p)
            inv_lines.append(InvoiceLineItem(description=d, quantity=q, unit_price=p, tax=money(net * rate), total=net))
        subtotal = sum((l.total for l in inv_lines), Decimal("0"))
        tax = sum((l.tax for l in inv_lines), Decimal("0"))
        return Invoice(
            invoice_number="",  # assigned in _number_invoices, in date order per supplier
            supplier_name=name or supplier.name,
            po_reference=po_ref,
            invoice_date=invoice_date,
            due_date=invoice_date + timedelta(days=supplier.terms_days),
            line_items=inv_lines,
            subtotal=subtotal,
            tax_amount=tax,
            total_amount=subtotal + tax,
            currency="GBP",
        )

    def _invoice_date(self, po: PurchaseOrder, gr: GoodsReceipt | None, delay: tuple[int, int] = (0, 14)) -> date:
        anchor = gr.receipt_date if gr else po.delivery_date
        return anchor + timedelta(days=self.rng.randint(*delay))

    def _add(self, invoice: Invoice, supplier: Supplier, code: ExceptionCode, true_po: str | None, **kw) -> None:
        self.records.append(_Record(invoice, supplier, code, true_po, **kw))

    def _supplier(self, goods_only: bool = False) -> Supplier:
        return self.rng.choice([s for s in SUPPLIERS if s.goods or not goods_only])

    def _standard_invoice(self, supplier: Supplier, po: PurchaseOrder, gr: GoodsReceipt | None, **kw) -> Invoice:
        return self.build_invoice(supplier, po_lines(po), self._invoice_date(po, gr), po_ref=po.po_number, **kw)

    # ------------------------------------------------------------------ scenarios

    def gen_clean(self, n: int) -> None:
        # Recurring monthly retainers: same supplier, same amount, invoices exactly 30 days apart.
        for s in self.rng.sample([s for s in SUPPLIERS if s.retainer], CLEAN_RECURRING_PAIRS):
            item = s.retainer
            line = (item.description, Decimal(self.rng.randint(*item.qty)), money(str(self.rng.uniform(*item.price))))
            first = self._date_between(YEAR_START, date(2026, 5, 31))
            for month in range(2):
                po = self.make_po(s, [line], order_date=first + timedelta(days=30 * month), lead_days=0)
                self.make_gr(po, receipt_offset=0, notes="Service completed as scheduled")
                inv = self.build_invoice(s, [line], po.delivery_date + timedelta(days=3), po_ref=po.po_number)
                self._add(inv, s, ExceptionCode.CLEAN, po.po_number, variant="recurring_retainer",
                          edge_cases=["recurring_similar_invoice"],
                          notes="Legitimate monthly invoice; same supplier and amount as another invoice 30 days apart")

        remaining = n - 2 * CLEAN_RECURRING_PAIRS
        special = self.rng.sample(range(remaining), CLEAN_BENIGN_NAME + CLEAN_PO_FORMAT)
        benign, fmt = set(special[:CLEAN_BENIGN_NAME]), set(special[CLEAN_BENIGN_NAME:])
        for i in range(remaining):
            s = self._supplier()
            po = self.make_po(s)
            gr = self.make_gr(po)
            inv = self._standard_invoice(s, po, gr)
            kw: dict = {}
            if i in benign:
                inv.supplier_name = benign_name_variant(s.name, self.rng)
                kw = dict(variant="benign_name_variant", edge_cases=["benign_name_variant"],
                          notes=f"Supplier name '{inv.supplier_name}' is a formatting variant of '{s.name}'")
            elif i in fmt:
                inv.po_reference = po_ref_format_variant(po.po_number, self.rng)
                kw = dict(variant="po_ref_format_variant", edge_cases=["po_ref_format_variant"],
                          notes=f"PO reference '{inv.po_reference}' is a formatting variant of {po.po_number}")
            self._add(inv, s, ExceptionCode.CLEAN, po.po_number, **kw)

    def gen_e01(self, n: int) -> None:
        """Amount variance within tolerance: a minor unit-price adjustment on one line."""
        for _ in range(n):
            s = self._supplier()
            while True:
                lines = self._lines_where(s, lambda _: True, max_total=E01_MAX_PO_TOTAL)
                adjusted = self._within_tolerance_variance(lines)
                if adjusted:
                    break
            new_lines, delta = adjusted
            po = self.make_po(s, lines)
            gr = self.make_gr(po)
            inv = self.build_invoice(s, new_lines, self._invoice_date(po, gr), po_ref=po.po_number)
            limit = self.settings.default_tolerance.limit_for(po.total_amount)
            self._add(inv, s, ExceptionCode.E01, po.po_number, variant="price_adjustment",
                      notes=f"Subtotal differs from PO by £{delta:+} ({pct(delta, po.total_amount)}); tolerance £{money(limit)}")

    def _within_tolerance_variance(self, lines: list[Line]) -> tuple[list[Line], Decimal] | None:
        total = lines_total(lines)
        limit = self.settings.default_tolerance.limit_for(total)
        lo, hi = total * Decimal("0.001"), limit * Decimal("0.9")
        if lo >= hi:
            return None
        for _ in range(20):
            target = Decimal(str(self.rng.uniform(float(lo), float(hi))))
            sign = 1 if self.rng.random() < 0.75 else -1
            for i in self.rng.sample(range(len(lines)), len(lines)):
                d, q, p = lines[i]
                new_p = money(p + sign * target / q)
                if new_p <= 0 or new_p == p:
                    continue
                delta = money(q * new_p) - money(q * p)
                if lo <= abs(delta) <= hi:
                    new_lines = list(lines)
                    new_lines[i] = (d, q, new_p)
                    return new_lines, delta
        return None

    def gen_e02(self, n: int) -> None:
        """Amount variance of 3-15%: pricing error applied across all lines."""
        no_gr = set(self.rng.sample(range(n), E02_NO_GR))
        for i in range(n):
            s = self._supplier()
            while True:
                lines = self._lines_where(s, lambda _: True)
                total = lines_total(lines)
                sign = 1 if self.rng.random() < 0.8 else -1
                factor = 1 + sign * Decimal(str(self.rng.uniform(0.03, 0.15)))
                new_lines = [(d, q, money(p * factor)) for d, q, p in lines]
                delta = lines_total(new_lines) - total
                if (Decimal("0.025") <= abs(delta) / total <= Decimal("0.155")
                        and abs(delta) > self.settings.default_tolerance.limit_for(total)):
                    break
            po = self.make_po(s, lines)
            gr = None if i in no_gr else self.make_gr(po)
            inv = self.build_invoice(s, new_lines, self._invoice_date(po, gr), po_ref=po.po_number)
            self._add(inv, s, ExceptionCode.E02, po.po_number,
                      variant="price_error_no_gr" if gr is None else "price_error",
                      edge_cases=["no_goods_receipt"] if gr is None else [],
                      notes=f"Subtotal differs from PO by £{delta:+} ({pct(delta, total)})")

    def gen_e03(self, n: int) -> None:
        """Partial delivery: GR received less than PO; invoice bills the full PO quantity."""
        notes_only = set(self.rng.sample(range(n), E03_NOTES_ONLY))
        for i in range(n):
            s = self._supplier(goods_only=True)
            lines = self._lines_where(s, lambda ls: any(q >= 2 for _, q, _ in ls))
            eligible = [j for j, (_, q, _) in enumerate(lines) if q >= 2]
            short_idx = self.rng.sample(eligible, 2 if len(eligible) > 1 and self.rng.random() < 0.2 else 1)
            shortfall = {j: self.rng.randint(1, max(1, int(lines[j][1]) // 2)) for j in short_idx}
            first = short_idx[0]
            fill = dict(k=shortfall[first], item=lines[first][0], box=self.rng.randint(1, 6))

            if i in notes_only:
                po = self.make_po(s, lines)
                gr = self.make_gr(po, notes=self.rng.choice(NOTES_ONLY_GR_NOTES).format(**fill))
                kw = dict(variant="gr_notes_only", edge_cases=["gr_notes_only"],
                          notes=f"GR structured quantities show full receipt, but notes record {fill['k']} units returned")
            else:
                po = self.make_po(s, lines, status=POStatus.PARTIALLY_FULFILLED)
                note = self.rng.choice(SHORTFALL_GR_NOTES).format(**fill) if self.rng.random() < 0.6 else ""
                gr = self.make_gr(po, shortfall=shortfall, notes=note)
                kw = dict(variant="partial_delivery",
                          notes="GR short on " + ", ".join(f"line {j + 1} by {k}" for j, k in shortfall.items()))
            self._add(self._standard_invoice(s, po, gr), s, ExceptionCode.E03, po.po_number, **kw)

    def gen_e05(self) -> None:
        """Missing, corrupted, or no PO at all."""
        with_po = ["missing"] * E05_MISSING + ["corrupted"] * E05_CORRUPTED
        decoys = set(self.rng.sample(range(len(with_po)), E05_DECOYS))
        for i, kind in enumerate(with_po):
            s = self._supplier()
            po = self.make_po(s)
            gr = self.make_gr(po)
            inv = self._standard_invoice(s, po, gr)
            if kind == "missing":
                inv.po_reference = self.rng.choice([None, "", "N/A", "TBC"])
                variant = "missing"
            else:
                inv.po_reference, how = self._corrupt_ref(po.po_number)
                variant = f"corrupted_{how}"
            edges = ["ambiguous_candidates"] if i in decoys else []
            notes = f"PO reference {inv.po_reference!r}; true PO {po.po_number}"
            if i in decoys:
                decoy = self._decoy_po(s, po)
                notes += f"; competing PO {decoy.po_number} has same supplier and items, total within 8%"
            self._add(inv, s, ExceptionCode.E05, po.po_number, variant=variant, edge_cases=edges, notes=notes)

        for _ in range(E05_MAVERICK):
            s = self._supplier()
            inv = self.build_invoice(s, self._lines_where(s, lambda _: True),
                                     self._date_between(date(2026, 2, 1), date(2026, 8, 31)),
                                     po_ref=self.rng.choice([None, "", "Verbal order", "See email"]))
            self._add(inv, s, ExceptionCode.E05, None, variant="maverick", edge_cases=["no_po_exists"],
                      notes="Maverick spend: no PO was raised")

    def _corrupt_ref(self, po_number: str) -> tuple[str, str]:
        year, num = po_number[3:].split("-")
        for _ in range(100):
            how = self.rng.choice(["truncated", "transposed", "wrong_year", "dropped_digit"])
            if how == "truncated":
                ref = po_number[: -self.rng.randint(2, 3)]
            elif how == "transposed":
                pairs = [j for j in range(len(num) - 1) if num[j] != num[j + 1]]
                if not pairs:
                    continue
                j = self.rng.choice(pairs)
                ref = f"PO-{year}-{num[:j]}{num[j + 1]}{num[j]}{num[j + 2:]}"
            elif how == "wrong_year":
                ref = f"PO-2025-{num}"
            else:
                j = self.rng.randrange(len(num))
                ref = f"PO-{year}-{num[:j]}{num[j + 1:]}"
            if ref not in self._used_refs:
                self._used_refs.add(ref)  # never let a later PO take this number
                return ref, how
        raise RuntimeError("could not corrupt PO reference")

    def _decoy_po(self, s: Supplier, po: PurchaseOrder) -> PurchaseOrder:
        factor = 1 + self.rng.choice([-1, 1]) * Decimal(str(self.rng.uniform(0.02, 0.08)))
        lines = [(d, q, money(p * factor)) for d, q, p in po_lines(po)]
        decoy = self.make_po(s, lines, order_date=max(YEAR_START, po.order_date + timedelta(days=self.rng.randint(-45, 45))))
        if self.rng.random() < 0.5:
            self.make_gr(decoy)
        return decoy

    def gen_e06(self, n: int) -> None:
        """Late invoice against a PO that is already closed."""
        for _ in range(n):
            s = self._supplier()
            po = self.make_po(s, order_window=(YEAR_START, date(2026, 4, 15)), status=POStatus.CLOSED)
            gr = self.make_gr(po)
            inv = self.build_invoice(s, po_lines(po), self._invoice_date(po, gr, delay=(45, 110)), po_ref=po.po_number)
            self._add(inv, s, ExceptionCode.E06, po.po_number, variant="late_invoice",
                      notes=f"Invoiced {(inv.invoice_date - gr.receipt_date).days} days after receipt against a closed PO")

    def gen_e07(self, n: int) -> None:
        """Wrong VAT rate applied, or header tax miscalculated. Subtotal matches the PO."""
        for i in range(n):
            s = self._supplier()
            while True:
                po_draft_lines = self._lines_where(s, lambda _: True)
                correct = sum((money(money(q * p) * self.settings.vat_rate) for _, q, p in po_draft_lines), Decimal("0"))
                if i < E07_WRONG_RATE:
                    rate = self.rng.choice([Decimal("0.05"), Decimal("0.175"), Decimal("0.15"), Decimal("0")])
                    wrong = sum((money(money(q * p) * rate) for _, q, p in po_draft_lines), Decimal("0"))
                    variant, notes = "wrong_rate", f"VAT charged at {(rate * 100).normalize():f}% instead of 20%"
                else:
                    wrong, variant = self._miscalculated_tax(po_draft_lines, correct)
                    notes = f"Header tax £{wrong} vs £{correct} recalculated from lines"
                if wrong >= 0 and abs(wrong - correct) >= 1:
                    break
            po = self.make_po(s, po_draft_lines)
            gr = self.make_gr(po)
            inv = self._standard_invoice(s, po, gr, vat_rate=rate if variant == "wrong_rate" else None)
            if variant != "wrong_rate":
                inv.tax_amount = wrong
                inv.total_amount = inv.subtotal + wrong
            self._add(inv, s, ExceptionCode.E07, po.po_number, variant=variant, notes=notes)

    def _miscalculated_tax(self, lines: list[Line], correct: Decimal) -> tuple[Decimal, str]:
        subtotal = lines_total(lines)
        how = self.rng.choice(["transposed_digits", "vat_on_gross", "arithmetic_slip", "line_omitted"])
        if how == "transposed_digits":
            digits = f"{correct:.2f}".replace(".", "")
            pairs = [j for j in range(len(digits) - 1) if digits[j] != digits[j + 1]]
            if not pairs:
                return correct, how
            j = self.rng.choice(pairs)
            return money(Decimal(digits[:j] + digits[j + 1] + digits[j] + digits[j + 2:]) / 100), how
        if how == "vat_on_gross":
            return money(subtotal * (1 + self.settings.vat_rate) * self.settings.vat_rate), how
        if how == "arithmetic_slip":
            return correct + self.rng.choice([-1, 1]) * Decimal(self.rng.choice([10, 100, 1000])), how
        if len(lines) < 2:
            return correct, how
        _, q, p = self.rng.choice(lines)
        return money((subtotal - money(q * p)) * self.settings.vat_rate), how

    def gen_e08(self, n: int) -> None:
        """Supplier name differs substantively from the PO (different or related legal entity)."""
        kinds = [E08_KINDS[i % len(E08_KINDS)] for i in range(n)]
        self.rng.shuffle(kinds)
        for kind in kinds:
            s = self._supplier()
            po = self.make_po(s)
            gr = self.make_gr(po)
            name = substantive_name_variant(s, kind, self.rng)
            inv = self._standard_invoice(s, po, gr, name=name)
            self._add(inv, s, ExceptionCode.E08, po.po_number, variant=kind,
                      edge_cases=["ambiguous_name_typo"] if kind == "typo" else [],
                      notes=f"Invoice supplier '{name}' vs PO supplier '{s.name}'")

    def gen_unbilled(self, n: int) -> None:
        for _ in range(n):
            po = self.make_po(self._supplier())
            if self.rng.random() < 0.5:
                self.make_gr(po)

    # ------------------------------------------------------------------ finalise

    def _number_invoices(self) -> None:
        """Each supplier numbers invoices in date order, with gaps (they bill other customers too)."""
        counters = {s.supplier_id: self.rng.randint(100, 9000) for s in SUPPLIERS}
        for rec in sorted(self.records, key=lambda r: r.invoice.invoice_date):
            sid = rec.supplier.supplier_id
            counters[sid] += self.rng.randint(1, 40)
            d = rec.invoice.invoice_date
            rec.invoice.invoice_number = rec.supplier.invoice_format.format(
                abbr=rec.supplier.abbr, n=counters[sid], yyyy=d.year, yy=d.strftime("%y")
            )

    def gen_e04(self, n: int) -> None:
        """Resubmission of a previously invoiced clean invoice: same or ±1 day date."""
        pool = [r for r in self.records if r.code == ExceptionCode.CLEAN and r.variant is None]
        for orig in self.rng.sample(pool, n):
            inv = orig.invoice.model_copy(deep=True)
            shift = self.rng.choice([-1, 0, 0, 1])
            inv.invoice_date += timedelta(days=shift)
            inv.due_date += timedelta(days=shift)
            same_number = self.rng.random() < 0.5
            if not same_number:
                inv.invoice_number = self.rng.choice(["{}-R", "{}/1", "{}A", "R{}"]).format(inv.invoice_number)
            variant = ("exact_resubmission" if shift == 0 else "resubmitted_date_shift") if same_number else "renumbered"
            self.records.append(_Record(
                inv, orig.supplier, ExceptionCode.E04, orig.true_po, variant=variant, duplicate_of=orig,
                notes=f"Duplicate of {orig.invoice.invoice_number} ({orig.invoice.invoice_date}), date shift {shift:+d} day(s)",
            ))

    def _order(self) -> None:
        """Shuffle into a processing order where every duplicate arrives after its original."""
        order = [r for r in self.records if r.duplicate_of is None]
        self.rng.shuffle(order)
        for dup in (r for r in self.records if r.duplicate_of is not None):
            order.insert(self.rng.randint(order.index(dup.duplicate_of) + 1, len(order)), dup)
        for i, rec in enumerate(order, 1):
            rec.doc_id = f"DOC-{i:04d}"
        self.records = order

    def build(self) -> Dataset:
        self.gen_clean(DISTRIBUTION["clean"])
        self.gen_e01(DISTRIBUTION["E01"])
        self.gen_e02(DISTRIBUTION["E02"])
        self.gen_e03(DISTRIBUTION["E03"])
        assert E05_MISSING + E05_CORRUPTED + E05_MAVERICK == DISTRIBUTION["E05"]
        self.gen_e05()
        self.gen_e06(DISTRIBUTION["E06"])
        self.gen_e07(DISTRIBUTION["E07"])
        self.gen_e08(DISTRIBUTION["E08"])
        self.gen_unbilled(UNBILLED_POS)
        self._number_invoices()
        self.gen_e04(DISTRIBUTION["E04"])
        self._order()

        counts = Counter(r.code.value for r in self.records)
        assert counts == Counter(DISTRIBUTION), f"distribution mismatch: {counts}"

        return Dataset(
            purchase_orders=sorted(self.pos.values(), key=lambda p: p.po_number),
            goods_receipts=sorted(self.grs, key=lambda g: g.gr_number),
            invoices=[InvoiceDoc(doc_id=r.doc_id, invoice=r.invoice) for r in self.records],
            labels=[
                GroundTruth(
                    doc_id=r.doc_id,
                    invoice_number=r.invoice.invoice_number,
                    code=r.code,
                    action=expected_action(r.code, self.settings),
                    true_po_number=r.true_po,
                    duplicate_of=r.duplicate_of.doc_id if r.duplicate_of else None,
                    variant=r.variant,
                    edge_cases=r.edge_cases,
                    notes=r.notes,
                )
                for r in self.records
            ],
        )

    def manifest(self, ds: Dataset) -> dict:
        return {
            "generator_version": GENERATOR_VERSION,
            "seed": self.seed,
            "counts": {
                "invoices": len(ds.invoices),
                "purchase_orders": len(ds.purchase_orders),
                "goods_receipts": len(ds.goods_receipts),
            },
            "by_code": dict(sorted(Counter(l.code.value for l in ds.labels).items())),
            "by_action": dict(sorted(Counter(l.action.value for l in ds.labels).items())),
            "by_variant": dict(sorted(Counter(f"{l.code.value}/{l.variant}" for l in ds.labels if l.variant).items())),
            "edge_cases": dict(sorted(Counter(e for l in ds.labels for e in l.edge_cases).items())),
            "assumptions": {
                "vat_rate": str(self.settings.vat_rate),
                "tolerance_pct": str(self.settings.default_tolerance.pct),
                "tolerance_abs_gbp": str(self.settings.default_tolerance.absolute),
                "amount_comparison": "invoice subtotal (pre-tax) vs PO total_amount (pre-tax)",
                "invoice_line_total": "net (quantity x unit_price), excl. tax",
            },
        }


# ---------------------------------------------------------------------- helpers


def lines_total(lines: list[Line]) -> Decimal:
    return sum((money(q * p) for _, q, p in lines), Decimal("0"))


def po_lines(po: PurchaseOrder) -> list[Line]:
    return [(l.description, l.quantity, l.unit_price) for l in po.line_items]


def pct(delta: Decimal, total: Decimal) -> str:
    return f"{delta / total * 100:+.2f}%"


def benign_name_variant(name: str, rng: random.Random) -> str:
    """Formatting-only differences an analyst would accept as the same supplier."""
    options = []
    for suffix, alts in (("Co Ltd", ["Company Limited", "Co. Ltd", "Co"]),
                         ("Ltd", ["Limited", "Ltd.", "LTD", ""]),
                         ("plc", ["PLC", "Plc", ""]),
                         ("LLP", ["", "L.L.P."])):
        if name.endswith(" " + suffix):
            stem = name[: -len(suffix) - 1]
            options += [f"{stem} {a}".strip() for a in alts]
            break
    if "&" in name:
        options.append(name.replace("&", "and"))
    options.append(name.upper())
    return rng.choice(options)


def substantive_name_variant(s: Supplier, kind: str, rng: random.Random) -> str:
    stem = legal_stem(s.name)
    if kind == "initialism":
        return f"{s.abbr} Ltd"
    if kind == "subsidiary":
        return f"{stem} ({s.region}) Ltd"
    if kind == "parent":
        return f"{stem.split()[0]} Group Holdings plc"
    if kind == "trading_name":
        return s.trading_name
    return typo(stem, 2, rng) + s.name[len(stem):]


def typo(text: str, edits: int, rng: random.Random) -> str:
    out = text
    while out.lower() == text.lower():
        out = text
        for _ in range(edits):
            positions = [j for j in range(1, len(out) - 1) if out[j].isalpha() and out[j + 1].isalpha()]
            j = rng.choice(positions)
            op = rng.choice(["delete", "swap", "double"])
            if op == "delete":
                out = out[:j] + out[j + 1:]
            elif op == "swap":
                out = out[:j] + out[j + 1] + out[j] + out[j + 2:]
            else:
                out = out[:j] + out[j] + out[j:]
    return out


def po_ref_format_variant(po_number: str, rng: random.Random) -> str:
    year, num = po_number[3:].split("-")
    return rng.choice([f"PO{year}{num}", f"po-{year}-{num}", f"PO {year} {num}", f"PO#{year}-{num}", f"PO/{year}/{num}"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    gen = Generator(seed=args.seed)
    ds = gen.build()
    manifest = gen.manifest(ds)
    ds.write(args.out, manifest)
    write_documents(ds.invoices, args.out / "documents")
    c = manifest["counts"]
    print(f"Wrote {c['invoices']} invoices, {c['purchase_orders']} POs, {c['goods_receipts']} goods receipts to {args.out}")
    for code, count in manifest["by_code"].items():
        print(f"  {code:>5}: {count}")


if __name__ == "__main__":
    main()
