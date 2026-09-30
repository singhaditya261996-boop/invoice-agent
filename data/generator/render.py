"""Render synthetic invoices as plain-text documents for extraction testing (PRD §3.1 Step 1, §5.2).

Three layouts, assigned per supplier, so the extractor sees varied labelling, date formats
and number formats. The structured invoice in invoices.json is the extraction ground truth.
"""

from __future__ import annotations

import zlib
from decimal import Decimal
from pathlib import Path

from app.models import Invoice

BILL_TO = "Aldermoor Group plc, Accounts Payable, 14 Canal Street, Leeds LS1 4AB"


def _gbp(x: Decimal) -> str:
    return f"£{x:,.2f}"


def _qty(q: Decimal) -> str:
    text = f"{q:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _terms(inv: Invoice) -> str:
    return f"Net {(inv.due_date - inv.invoice_date).days}"


def layout_table(inv: Invoice) -> str:
    w = max(44, *(len(l.description) for l in inv.line_items))
    rule = "-" * (w + 44)
    rows = [f"{l.description:<{w}} {_qty(l.quantity):>6} {_gbp(l.unit_price):>11} {_gbp(l.tax):>11} {_gbp(l.total):>12}"
            for l in inv.line_items]
    po = "" if inv.po_reference is None else f"Customer PO:   {inv.po_reference}\n"
    return (
        f"{inv.supplier_name}\nTAX INVOICE\n\n"
        f"Invoice No:    {inv.invoice_number}\n"
        f"Invoice Date:  {inv.invoice_date:%d/%m/%Y}\n"
        f"Due Date:      {inv.due_date:%d/%m/%Y}\n{po}"
        f"Bill To:       {BILL_TO}\n\n"
        f"{'Description':<{w}} {'Qty':>6} {'Unit Price':>11} {'VAT':>11} {'Net':>12}\n{rule}\n"
        + "\n".join(rows)
        + f"\n{rule}\n{'Subtotal':>{w + 30}} {_gbp(inv.subtotal):>13}\n{'VAT':>{w + 30}} {_gbp(inv.tax_amount):>13}\n"
        f"{'TOTAL DUE':>{w + 30}} {_gbp(inv.total_amount):>13}\n\nPayment terms: {_terms(inv)}. Please quote the invoice number.\n"
    )


def layout_letter(inv: Invoice) -> str:
    lines = "\n".join(
        f"  - {_qty(l.quantity)} x {l.description} @ GBP {l.unit_price} = GBP {l.total} (VAT GBP {l.tax})"
        for l in inv.line_items)
    po = "" if inv.po_reference is None else f"Your order reference: {inv.po_reference}\n"
    return (
        f"From: {inv.supplier_name}\nTo: {BILL_TO}\n\n"
        f"INVOICE {inv.invoice_number}\nDated {inv.invoice_date.day} {inv.invoice_date:%B %Y}\n{po}\n"
        f"Supplied:\n{lines}\n\n"
        f"Net amount: GBP {inv.subtotal}\nVAT: GBP {inv.tax_amount}\nAmount payable: GBP {inv.total_amount}\n\n"
        f"Payment due by {inv.due_date.day} {inv.due_date:%B %Y} ({_terms(inv)}).\n"
    )


def layout_compact(inv: Invoice) -> str:
    lines = "\n".join(f"{i + 1}. {l.description} | qty {_qty(l.quantity)} | unit {l.unit_price} | "
                      f"net {l.total} | vat {l.tax}" for i, l in enumerate(inv.line_items))
    po = "" if inv.po_reference is None else f"Purchase Order Ref: {inv.po_reference}\n"
    return (
        f"Invoice | {inv.supplier_name}\n"
        f"Ref: {inv.invoice_number}   Issued: {inv.invoice_date.isoformat()}   Due: {inv.due_date.isoformat()}\n{po}"
        f"Customer: {BILL_TO}\nCurrency: {inv.currency}\n\n{lines}\n\n"
        f"Net {inv.subtotal} | VAT {inv.tax_amount} | Gross {inv.total_amount}\n"
    )


LAYOUTS = (layout_table, layout_letter, layout_compact)


def render(inv: Invoice) -> str:
    """Layout is fixed per supplier name, as a real supplier's template would be."""
    return LAYOUTS[zlib.crc32(inv.supplier_name.encode()) % len(LAYOUTS)](inv)


def write_documents(invoices, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for doc in invoices:
        (out_dir / f"{doc.doc_id}.txt").write_text(render(doc.invoice))
