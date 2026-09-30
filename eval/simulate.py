"""Stand-in LLM for evaluations that must not call the API.

Two uses:
1. Cost estimation: answers extraction requests with the ground truth (so the rest of the
   pipeline runs normally) and records the size of every request the live agent would send.
2. Robustness to extraction errors (failure taxonomy: extraction hallucination): with
   noise_rate > 0, injects realistic misreads into extracted fields, reported at the same
   high self-confidence a real model might claim. Tests whether downstream safeguards
   (arithmetic consistency checks, three-way match) stop a misread invoice being auto-approved.

Only extraction is simulated. Other LLM tasks return None, so the rule-based fallbacks run.
"""

from __future__ import annotations

import json
import random
import threading
from dataclasses import dataclass
from decimal import Decimal

from app.models import Invoice, LLMCall

SELF_REPORTED_CONFIDENCE = 0.95
LOOKALIKE_DIGITS = {"1": "7", "7": "1", "3": "8", "8": "3", "5": "6", "6": "5", "0": "8", "2": "7", "4": "9", "9": "4"}
# Fields where a misread could lead to paying the wrong amount or the wrong party. (Per-line VAT is
# informational: the amount paid is the header total.)
MATERIAL = ("subtotal", "tax_amount", "total_amount", "unit_price", "quantity", "total", "po_reference",
            "supplier_name")


@dataclass
class Perturbation:
    kind: str
    field: str
    before: str
    after: str

    @property
    def material(self) -> bool:
        return self.field.split(".")[-1] in MATERIAL


@dataclass
class Request:
    task: str
    input_chars: int
    expected_output_chars: int


class SimulatedLLM:
    def __init__(self, truth_by_document: dict[str, list[tuple[str, Invoice]]], noise_rate: float = 0.0,
                 seed: int = 0) -> None:
        # Document text -> [(doc_id, invoice)] in processing order. An exact resubmission (E04) renders
        # to identical text, so the nth request for a text is the nth document with that text.
        self.truth = truth_by_document
        self._seen: dict[str, int] = {}
        self.noise_rate = noise_rate
        self.rng = random.Random(seed)
        self.calls: list[LLMCall] = []
        self.requests: list[Request] = []
        self.perturbations: dict[str, Perturbation] = {}
        self._lock = threading.Lock()

    def json(self, task: str, system: str, content, schema: dict) -> dict | None:
        self.calls.append(LLMCall(step=task, model="simulated", error=None if task == "extract" else "simulated"))
        text = content if isinstance(content, str) else json.dumps(content)
        out = None
        if task == "extract":
            doc = text.removeprefix("<invoice_document>\n").removesuffix("\n</invoice_document>")
            nth = self._seen.get(doc, 0)
            self._seen[doc] = nth + 1
            doc_id, invoice = self.truth[doc][nth]
            out = invoice.model_dump(mode="json") | {"unreadable_fields": [], "confidence": SELF_REPORTED_CONFIDENCE}
            with self._lock:
                if self.noise_rate and self.rng.random() < self.noise_rate:
                    self.perturbations[doc_id] = self._perturb(out)
        expected = {"extract": len(json.dumps(out)) if out else 0, "gr_notes": 160, "classify": 300,
                    "brief": 900}.get(task, 300)
        self.requests.append(Request(task, len(system) + len(text) + len(json.dumps(schema)), expected))
        return out

    # ------------------------------------------------------------------ misreads

    def _perturb(self, data: dict) -> Perturbation:
        amounts = ["subtotal", "tax_amount", "total_amount"] + \
            [f"line_items.{i}.{f}" for i in range(len(data["line_items"])) for f in ("total", "unit_price", "tax")]
        options = [
            ("decimal_shift", amounts), ("digit_transposed", amounts), ("digit_lookalike", amounts),
            ("quantity_misread", [f"line_items.{i}.quantity" for i in range(len(data["line_items"]))]),
            ("supplier_typo", ["supplier_name"]), ("date_misread", ["invoice_date"]),
        ]
        if data["po_reference"] and any(c.isdigit() for c in data["po_reference"]):
            options.append(("po_ref_digit", ["po_reference"]))
        for _ in range(20):
            kind, fields = self.rng.choice(options)
            field = self.rng.choice(fields)
            before = str(_get(data, field))
            after = self._misread(kind, before)
            if after is not None and after != before:
                _set(data, field, after)
                return Perturbation(kind, field, before, after)
        raise RuntimeError("could not perturb invoice")

    def _misread(self, kind: str, value: str) -> str | None:
        r = self.rng
        digits = [i for i, c in enumerate(value) if c.isdigit()]
        if kind == "decimal_shift":
            return str((Decimal(value) * r.choice([Decimal(10), Decimal("0.1")])).quantize(Decimal("0.01")))
        if kind in ("digit_transposed",):
            pairs = [i for i in digits[:-1] if i + 1 in digits and value[i] != value[i + 1]]
            if not pairs:
                return None
            i = r.choice(pairs)
            return value[:i] + value[i + 1] + value[i] + value[i + 2:]
        if kind in ("digit_lookalike", "po_ref_digit", "quantity_misread"):
            i = r.choice(digits) if digits else None
            return None if i is None else value[:i] + LOOKALIKE_DIGITS[value[i]] + value[i + 1:]
        if kind == "supplier_typo":
            i = r.randrange(1, len(value) - 1)
            return value[:i] + value[i + 1:]
        if kind == "date_misread":
            y, m, d = value.split("-")
            return f"{y}-{d}-{m}" if int(d) <= 12 and d != m else f"{y}-{m}-{int(d) % 28 + 1:02d}"
        return None


def _get(data: dict, path: str):
    for part in path.split("."):
        data = data[int(part)] if part.isdigit() else data[part]
    return data


def _set(data: dict, path: str, value) -> None:
    *head, last = path.split(".")
    for part in head:
        data = data[int(part)] if part.isdigit() else data[part]
    data[last] = value
