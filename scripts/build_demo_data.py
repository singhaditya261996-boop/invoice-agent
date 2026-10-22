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

# The policy sandbox needs a server to re-run a batch, which the hosted demo does not have, so the
# scenarios it offers are precomputed here. These lists must match POLICY_GRID in the frontend.
TOLERANCES = [("0.005", "25"), ("0.01", "50"), ("0.02", "150"), ("0.05", "500")]
APPROVAL_CONFIDENCES = [0.85, 0.90, 0.95, 0.99]
AUTONOMY_SETS = [["E01", "E04"], ["E01", "E03", "E04"], ["E01", "E03", "E04", "E07"]]

# A category needs 40 reviews before the feedback loop will recommend anything, and a single batch
# cannot supply that for most categories — evidence accrues across batches. So the demo ships a
# simulated quarter of review history, labelled as simulated wherever it is shown.
# (code, reviews, override rate, share of those overrides that reverse an autonomous decision)
SIMULATED_HISTORY = [
    ("clean", 400, 0.01, 0.2),
    ("E01", 200, 0.06, 0.1),
    ("E02", 120, 0.09, 0.0),
    ("E03", 150, 0.05, 0.0),
    ("E04", 80, 0.09, 0.7),
    ("E05", 140, 0.22, 0.0),
    ("E06", 30, 0.10, 0.0),
    ("E07", 90, 0.12, 0.0),
    ("E08", 60, 0.10, 0.0),
]


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":")))


def simulated_feedback(settings: Settings):
    """A plausible quarter of analyst review history, so the demo can show the mechanism working."""
    import random
    from datetime import datetime, timezone

    from app.feedback import analyse
    from app.models import Action, Decision, ExceptionCode, OverrideReason, Review

    rng = random.Random(11)
    autonomous = {"clean", "E01", "E04"}
    reviews = {}
    for code, count, override_rate, reversal_share in SIMULATED_HISTORY:
        action = Action.AUTO_REJECT if code == "E04" else (
            Action.AUTO_APPROVE if code in autonomous else Action.ESCALATE)
        for i in range(count):
            doc = f"HIST-{code}-{i}"
            override = rng.random() < override_rate
            reverses = override and rng.random() < reversal_share
            decision = (Decision.APPROVE if action == Action.AUTO_REJECT else Decision.REJECT) if reverses \
                else (Decision.REJECT if action == Action.AUTO_REJECT else Decision.APPROVE)
            reviews[doc] = Review(
                doc_id=doc, invoice_number=doc, original_code=ExceptionCode(code), original_action=action,
                new_code=ExceptionCode.CLEAN if override else ExceptionCode(code), decision=decision,
                is_override=override, reason=OverrideReason.WRONG_CATEGORY if override else None,
                analyst="demo", created_at=datetime.now(timezone.utc))
    report = analyse({}, reviews, settings)
    report.note = (f"Simulated review history: {len(reviews)} analyst decisions across earlier batches. "
                   "A category needs 40 reviews before this will recommend anything, which one batch "
                   "rarely supplies.")
    return report


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

        for ti, (pct, absolute) in enumerate(TOLERANCES):
            for ci, confidence in enumerate(APPROVAL_CONFIDENCES):
                for ai, autonomy in enumerate(AUTONOMY_SETS):
                    body = {"tolerance_pct": pct, "tolerance_absolute": absolute,
                            "auto_approve_confidence": confidence, "auto_resolvable": autonomy}
                    write(OUT / "policy" / f"{ti}-{ci}-{ai}.json",
                          client.post(f"/batches/{bid}/simulate", json=body).json())

        write(OUT / "feedback.json", simulated_feedback(settings).model_dump(mode="json"))

        size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
        scenarios = len(TOLERANCES) * len(APPROVAL_CONFIDENCES) * len(AUTONOMY_SETS)
        print(f"Wrote {len(list(OUT.rglob('*.json')))} JSON files for {len(rows)} invoices, "
              f"{len(pos)} POs and {scenarios} policy scenarios ({size / 1024:.0f} KB) "
              f"to {OUT.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
