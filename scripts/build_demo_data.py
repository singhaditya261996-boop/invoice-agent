"""Freeze a demo batch into static JSON for the hosted (API-less) build.

The hosted demo on GitHub Pages has no backend, so the UI reads these files instead. They are
produced by driving the real API through its own endpoints, so the shapes cannot drift from the
live ones: whatever the server would return is what gets written.

    python -m scripts.build_demo_data

Output: app/frontend/public/demo/ (committed, so `npm run build` needs no Python).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import RunMode, Settings

OUT = Path(__file__).resolve().parents[1] / "app" / "frontend" / "public" / "demo"
# Every invoice whose model responses were recorded by the live pilots.
INVOICE_LIMIT = 24


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":")))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(mode=RunMode.DEMO, llm_provider="google", google_model="gemini-3-flash-preview",
                            review_log_path=Path(tmp) / "reviews.jsonl")
        client = TestClient(create_app(settings))

        batch = client.post("/batches/demo", json={"mode": "demo", "input": "documents",
                                                   "limit": INVOICE_LIMIT}).json()
        bid = batch["id"]
        batch = client.get(f"/batches/{bid}").json()

        if OUT.exists():
            shutil.rmtree(OUT)
        write(OUT / "config.json", client.get("/config").json())
        write(OUT / "batch.json", batch)
        write(OUT / "batches.json", [batch])
        write(OUT / "dashboard.json", client.get(f"/batches/{bid}/dashboard").json())
        write(OUT / "audit.csv", client.get(f"/batches/{bid}/audit", params={"format": "csv"}).text)

        rows = client.get(f"/batches/{bid}/results", params={"limit": 1000}).json()
        write(OUT / "results.json", rows)

        pos: set[str] = set()
        for row in rows:
            doc = row["doc_id"]
            detail = client.get(f"/batches/{bid}/results/{doc}").json()
            write(OUT / "results" / f"{doc}.json", detail)
            write(OUT / "sources" / f"{doc}.txt", client.get(f"/batches/{bid}/sources/{doc}").text)
            po = detail["result"].get("match", {}) or {}
            for candidate in [row.get("po_number")] + [c["po_number"] for c in po.get("candidates", [])]:
                if candidate:
                    pos.add(candidate)

        for po_number in sorted(pos):
            write(OUT / "purchase-orders" / f"{po_number}.json",
                  client.get(f"/batches/{bid}/purchase-orders/{po_number}").json())
            gr = client.get(f"/batches/{bid}/purchase-orders/{po_number}/goods-receipt")
            if gr.status_code == 200:
                write(OUT / "goods-receipts" / f"{po_number}.json", gr.json())

        size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
        print(f"Wrote {len(list(OUT.rglob('*.json')))} JSON files for {len(rows)} invoices "
              f"and {len(pos)} POs ({size / 1024:.0f} KB) to {OUT.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
