#!/usr/bin/env node

// Run the Home Depot own-vs-competitor benchmark (homedepot_competitors_compare.md).
//
// Reads the current dashboard snapshot (works offline; NocoDB not required),
// computes the market benchmark for the pilot category, writes the four-step
// outputs to outputs/, and augments the site snapshot with `marketBenchmark`
// so the new "市场对标" dashboard page renders without waiting for a NocoDB
// refresh.
//
//   Usage: node scripts/run_competitor_benchmark.mjs [category]

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildBenchmark, buildUnifiedTable } from "./competitor_benchmark.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const siteRoot = resolve(root, "outputs", "sonkuki_gsc_insights_site");
// The worker snapshot is the authoritative build output (written by
// build_dashboard_snapshot.mjs). Reading it here keeps the benchmark
// augmentation consistent with the latest review classification; public/ is
// refreshed by the export step below.
const snapshotPath = resolve(siteRoot, "worker", "dashboard_snapshot.js");
const workerSnapshotPath = resolve(siteRoot, "worker", "dashboard_snapshot.js");
const outputsDir = resolve(root, "outputs");
const category = process.argv[2] || "Pergola";

// Serialize an array of plain objects to CSV (no external dependency).
const csv = (rows) => {
  if (!rows.length) return "";
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const cell = (value) => {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [keys.join(","), ...rows.map((row) => keys.map((key) => cell(row[key])).join(","))].join("\n") + "\n";
};

const clean = (value) => String(value ?? "").trim();

// The worker snapshot is an ES module ("export const SNAPSHOT = {...};"), so
// extract the JSON payload between the first "{" and the matching trailing "}".
const readSnapshot = async () => {
  const text = await readFile(snapshotPath, "utf8");
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error(`Cannot parse snapshot at ${snapshotPath}`);
  return JSON.parse(text.slice(start, end + 1));
};

const snapshot = await readSnapshot();
const snapshotDate = (snapshot.generatedAt || "").slice(0, 10) || new Date().toISOString().slice(0, 10);

// Own SKUs whose title omits "Louvered" but are louvered products (same series
// as verifiable louvered sibling SKUs). Kept as an explicit, documented list.
const serenoLedOverrides = new Set(
  (snapshot.hdProducts || [])
    .filter((row) => /sereno series/i.test(row.name) && /solar-powered led/i.test(row.name) && !/louver/i.test(row.name))
    .map((row) => clean(row.itemId))
    .filter(Boolean),
);

const benchmark = buildBenchmark(snapshot, category, snapshotDate, serenoLedOverrides);

// Step 1 – unified product table (own + competitor, deduplicated, side-marked).
const unifiedTable = buildUnifiedTable({
  hdProducts: snapshot.hdProducts || [],
  competitorProducts: snapshot.competitor?.products || [],
  snapshotDate,
  ownLouveredOverrides: serenoLedOverrides,
});

// Step 2 – comparable group per own SKU.
const groupRows = benchmark.skus.map((sku) => ({
  item_id: sku.itemId, mpn: sku.mpn, name: sku.name, category: sku.category,
  group_key: sku.groupKey, tier: sku.tier, wide: sku.wide ? "yes" : "no",
  competitor_count: sku.competitorCount,
}));

// Step 3 – per-SKU core comparison.
const skuRows = benchmark.skus.map((sku) => ({
  item_id: sku.itemId, mpn: sku.mpn, name: sku.name, url: sku.url,
  group_key: sku.groupKey, tier: sku.tier, competitor_count: sku.competitorCount,
  price: sku.price, comp_median_price: sku.compMedianPrice, price_delta: sku.priceDelta,
  rating: sku.rating, comp_median_rating: sku.compMedianRating, rating_delta: sku.ratingDelta,
  review_count: sku.reviewCount, comp_median_reviews: sku.compMedianReviews, review_delta: sku.reviewDelta,
  own_lowstar_share: sku.ownLowStarShare, comp_lowstar_share: sku.compLowStarShare,
  own_top_themes: (sku.ownTopThemes || []).join(" | "), comp_top_themes: (sku.compTopThemes || []).join(" | "),
  action: sku.action, action_note: sku.actionNote,
}));

// Product units – the dashboard's Product Benchmark rows (SKUs sharing one
// comparable group are aggregated into one product unit).
const unitRows = benchmark.units.map((unit) => ({
  group_key: unit.groupKey, group_label: unit.groupLabel, tier: unit.tier, match_quality: unit.matchQuality,
  sku_count: unit.skuCount, mpns: unit.mpns.join(" | "),
  competitor_count: unit.competitorCount, competitor_listing_count: unit.competitorListingCount,
  competitor_brands: (unit.competitorBrands || []).join(" | "),
  price_min: unit.priceMin, price_max: unit.priceMax, price_median: unit.priceMedian,
  comp_median_price: unit.compMedianPrice,
  rating: unit.rating, comp_median_rating: unit.compMedianRating,
  review_count: unit.reviewCount, comp_median_reviews: unit.compMedianReviews,
  own_lowstar_share: unit.ownLowStarShare, comp_lowstar_share: unit.compLowStarShare,
  action: unit.action, confidence: unit.confidence,
  problem: unit.problem, evidence: unit.evidence, suggestion: unit.suggestion,
}));

const coverage = benchmark.coverage;
const coverageRows = [
  ["category", coverage.category],
  ["own_units", coverage.ownUnits],
  ["own_listings", coverage.ownListings],
  ["competitor_units", coverage.competitorUnits],
  ["competitor_listings", coverage.competitorListings],
  ["own_median_price", coverage.ownMedianPrice],
  ["competitor_median_price", coverage.competitorMedianPrice],
  ["own_avg_rating", coverage.ownAvgRating],
  ["competitor_avg_rating", coverage.competitorAvgRating],
  ["match_exact", coverage.matchExact],
  ["match_approximate", coverage.matchApproximate],
  ["match_none", coverage.matchNone],
];

await mkdir(outputsDir, { recursive: true });
const outputs = {
  unified: resolve(outputsDir, `competitor_benchmark_unified_${snapshotDate}.csv`),
  groups: resolve(outputsDir, `competitor_benchmark_groups_${snapshotDate}.csv`),
  units: resolve(outputsDir, `competitor_benchmark_units_${snapshotDate}.csv`),
  skus: resolve(outputsDir, `competitor_benchmark_skus_${snapshotDate}.csv`),
  coverage: resolve(outputsDir, `competitor_benchmark_coverage_${snapshotDate}.json`),
  actions: resolve(outputsDir, `competitor_benchmark_actions_${snapshotDate}.json`),
  full: resolve(outputsDir, `competitor_benchmark_${snapshotDate}.json`),
};
await writeFile(outputs.unified, csv(unifiedTable));
await writeFile(outputs.groups, csv(groupRows));
await writeFile(outputs.units, csv(unitRows));
await writeFile(outputs.skus, csv(skuRows));
await writeFile(outputs.coverage, JSON.stringify(coverage, null, 2));
await writeFile(outputs.actions, JSON.stringify({ snapshotDate, category, priorityActions: benchmark.priorityActions }, null, 2));
await writeFile(outputs.full, JSON.stringify(benchmark, null, 2));

// Augment the site snapshot so the "市场对标" page renders now. Preserve every
// existing field verbatim; only add `marketBenchmark`, inject the benchmark
// coverage quality check, and bump generatedAt.
if (JSON.stringify(benchmark).match(/reviewText|userName|userNickname|authorId|userLocation/)) {
  throw new Error("Benchmark blocked: PII field detected");
}
const siteSnapshot = await readSnapshot();
const coverageCheck = {
  id: "benchmark_coverage",
  label: "Pergola own units have a competitor benchmark",
  status: benchmark.units.every((row) => row.competitorCount > 0 || row.tier === "none") ? "pass" : "fail",
  detail: `${coverage.ownUnits} own units (${coverage.ownListings} listings) vs ${coverage.competitorUnits} competitor units (${coverage.competitorListings} listings) · ${coverage.matchExact} exact / ${coverage.matchApproximate} approximate / ${coverage.matchNone} none · ${benchmark.priorityActions.length} priority actions.`,
};
siteSnapshot.quality = {
  ...siteSnapshot.quality,
  checks: [...(siteSnapshot.quality?.checks || []).filter((check) => check.id !== "benchmark_coverage"), coverageCheck],
};
siteSnapshot.marketBenchmark = benchmark;
siteSnapshot.generatedAt = new Date().toISOString();
await writeFile(
  workerSnapshotPath,
  `// Generated by scripts/build_dashboard_snapshot.mjs. Do not edit by hand.\n// marketBenchmark augmented by scripts/run_competitor_benchmark.mjs.\nexport const SNAPSHOT = ${JSON.stringify(siteSnapshot)};\n`,
  "utf8",
);

// Refresh the static export (public/) so the local site and any Vercel deploy
// pick up the augmented snapshot.
if (existsSync(resolve(siteRoot, "scripts", "export_vercel_static.mjs"))) {
  await import(pathToFileURL(resolve(siteRoot, "scripts", "export_vercel_static.mjs")).href);
}

console.log(
  JSON.stringify({
    category, snapshotDate,
    ownUnits: benchmark.coverage.ownUnits, ownListings: benchmark.coverage.ownListings,
    competitorUnits: benchmark.coverage.competitorUnits, competitorListings: benchmark.coverage.competitorListings,
    match: `${benchmark.coverage.matchExact} exact / ${benchmark.coverage.matchApproximate} approx / ${benchmark.coverage.matchNone} none`,
    priorityActions: benchmark.priorityActions.length,
    vocSample: `${benchmark.voc.ownLowStarCount} own / ${benchmark.voc.compLowStarCount} comp low-star (insufficient=${benchmark.voc.sampleInsufficient})`,
    outputs: Object.values(outputs),
    siteSnapshot: workerSnapshotPath,
  }, null, 2),
);
