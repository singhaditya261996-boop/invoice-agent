"""Normalisation shared by matching and validation."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

PENNY = Decimal("0.01")
_LEGAL_SUFFIXES = {"ltd", "limited", "plc", "llp", "inc", "llc"}
_PO_DIGITS = re.compile(r"^(20\d{2})(\d{6})$")


def money(x: Decimal | int | str) -> Decimal:
    return Decimal(x).quantize(PENNY, rounding=ROUND_HALF_UP)


def gbp(x: Decimal, signed: bool = False) -> str:
    """£1,234.50; with signed=True, +£1,234.50 / -£1,234.50."""
    sign = ("+" if x >= 0 else "-") if signed else ("-" if x < 0 else "")
    return f"{sign}£{abs(x):,.2f}"


def canonical_po_ref(ref: str | None) -> str | None:
    """'PO2026004817', 'po-2026-004817', 'PO#2026-004817' -> 'PO-2026-004817'.

    Only reformats when every digit is present; truncated or altered references stay unmatched.
    """
    if not ref or not ref.strip():
        return None
    m = _PO_DIGITS.match(re.sub(r"\D", "", ref))
    if m and re.fullmatch(r"\s*po\W*\d{4}\W*\d{6}\s*", ref, flags=re.IGNORECASE):
        return f"PO-{m.group(1)}-{m.group(2)}"
    return ref.strip()


def supplier_key(name: str) -> str:
    """Formatting-insensitive supplier name: case, punctuation, '&', and legal suffixes ignored."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^\w\s]", "", s)
    tokens = ["co" if t == "company" else t for t in s.split()]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def description_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()
