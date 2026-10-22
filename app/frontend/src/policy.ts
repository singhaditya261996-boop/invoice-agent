// The policy sandbox's offered scenarios.
//
// The hosted demo has no server to re-run a batch, so these combinations are precomputed at build
// time by scripts/build_demo_data.py. **These lists must match TOLERANCES, APPROVAL_CONFIDENCES and
// AUTONOMY_SETS in that script**, since a scenario is addressed by its indices.

export interface PolicyIndices {
  tolerance: number;
  confidence: number;
  autonomy: number;
}

export const TOLERANCES = [
  { label: "Tight", detail: "0.5% or £25", pct: "0.005", absolute: "25" },
  { label: "Today", detail: "1% or £50", pct: "0.01", absolute: "50" },
  { label: "Loose", detail: "2% or £150", pct: "0.02", absolute: "150" },
  { label: "Very loose", detail: "5% or £500", pct: "0.05", absolute: "500" },
];

export const APPROVAL_CONFIDENCES = [
  { label: "85%", value: 0.85 },
  { label: "90%", value: 0.9 },
  { label: "95%", value: 0.95 },
  { label: "99%", value: 0.99 },
];

export const AUTONOMY_SETS = [
  { label: "Today", detail: "within tolerance and duplicates only", codes: ["E01", "E04"] },
  { label: "+ quantity", detail: "also partial deliveries (E03)", codes: ["E01", "E03", "E04"] },
  { label: "+ tax", detail: "also tax errors (E07)", codes: ["E01", "E03", "E04", "E07"] },
];

export const BASELINE: PolicyIndices = { tolerance: 1, confidence: 2, autonomy: 0 };

export const scenarioKey = (i: PolicyIndices) => `${i.tolerance}-${i.confidence}-${i.autonomy}`;

export const scenarioBody = (i: PolicyIndices) => ({
  tolerance_pct: TOLERANCES[i.tolerance].pct,
  tolerance_absolute: TOLERANCES[i.tolerance].absolute,
  auto_approve_confidence: APPROVAL_CONFIDENCES[i.confidence].value,
  auto_resolvable: AUTONOMY_SETS[i.autonomy].codes,
});
