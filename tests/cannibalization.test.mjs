import test from "node:test";
import assert from "node:assert/strict";
import { cannibalizationRows, isWellFormedRisk, riskCounts } from "../scripts/cannibalization.mjs";
import { SNAPSHOT } from "../outputs/sonkuki_gsc_insights_site/worker/dashboard_snapshot.js";

// Canonical GSC-shaped row used across the cannibalization tests.
const gsc = (query, canonical_page, impressions, clicks = 0, position = 5) => ({ query, canonical_page, impressions, clicks, position_weight: position * impressions });

test("single-URL query is LOW risk with that URL as primary", () => {
  const [row] = cannibalizationRows([gsc("sonkuki umbrella", "https://sonkuki.com/products/a", 500)]);
  assert.equal(row.risk, "LOW");
  assert.equal(row.primaryUrl, "https://sonkuki.com/products/a");
  assert.equal(row.primaryShare, 1);
  assert.equal(row.meaningfulCount, 1);
});

test("primary share >= 80% is LOW even with two meaningful URLs", () => {
  const [row] = cannibalizationRows([
    gsc("sonkuki umbrella", "https://sonkuki.com/products/a", 920),
    gsc("sonkuki umbrella", "https://sonkuki.com/products/b", 80), // 8% share but >= 50 impressions -> meaningful
  ]);
  assert.equal(row.risk, "LOW");
  assert.equal(row.meaningfulCount, 2);
  assert.equal(row.primaryShare, 0.92);
});

test("low-share, low-volume URLs are not meaningful competition", () => {
  const [row] = cannibalizationRows([
    gsc("sonkuki umbrella", "https://sonkuki.com/products/a", 190),
    gsc("sonkuki umbrella", "https://sonkuki.com/products/b", 10), // 5% share and < 50 impressions -> not meaningful
  ]);
  assert.equal(row.risk, "LOW");
  assert.equal(row.meaningfulCount, 1);
});

test("10% share makes a low-volume URL meaningful", () => {
  const [row] = cannibalizationRows([
    gsc("sonkuki umbrella", "https://sonkuki.com/products/a", 50),
    gsc("sonkuki umbrella", "https://sonkuki.com/products/b", 10), // 16.7% share -> meaningful despite 10 impressions
  ]);
  assert.equal(row.meaningfulCount, 2);
  assert.equal(row.primaryShare, 50 / 60);
  assert.equal(row.risk, "LOW"); // 83% primary share keeps it LOW
});

test("60-79% primary share with multiple meaningful URLs is MEDIUM", () => {
  const [row] = cannibalizationRows([
    gsc("sonkuki umbrella", "https://sonkuki.com/products/a", 700),
    gsc("sonkuki umbrella", "https://sonkuki.com/products/b", 300),
  ]);
  assert.equal(row.risk, "MEDIUM");
  assert.equal(row.meaningfulCount, 2);
  assert.equal(row.primaryShare, 0.7);
});

test("primary share below 60% with multiple meaningful URLs is HIGH", () => {
  const [row] = cannibalizationRows([
    gsc("sonkuki umbrella", "https://sonkuki.com/products/a", 400),
    gsc("sonkuki umbrella", "https://sonkuki.com/products/b", 300),
    gsc("sonkuki umbrella", "https://sonkuki.com/products/c", 300),
  ]);
  assert.equal(row.risk, "HIGH");
  assert.equal(row.meaningfulCount, 3);
  assert.equal(row.primaryShare, 0.4);
});

test("risk counts bucket every query exactly once", () => {
  const rows = cannibalizationRows([
    gsc("high", "https://sonkuki.com/p/1", 400),
    gsc("high", "https://sonkuki.com/p/2", 300),
    gsc("high", "https://sonkuki.com/p/3", 300),
    gsc("medium", "https://sonkuki.com/p/1", 700),
    gsc("medium", "https://sonkuki.com/p/2", 300),
    gsc("low", "https://sonkuki.com/p/1", 500),
  ]);
  assert.deepEqual(riskCounts(rows), { LOW: 1, MEDIUM: 1, HIGH: 1 });
});

test("snapshot cannibalization summary matches recomputation over VALID queries", () => {
  const summary = SNAPSHOT.cannibalization;
  const validRows = SNAPSHOT.gscRows.filter((row) => row.relevance_status === "VALID");
  const recomputed = cannibalizationRows(validRows);
  assert.equal(summary.analyzed, recomputed.length);
  assert.deepEqual(summary.byRisk, riskCounts(recomputed));
  assert.ok(recomputed.every(isWellFormedRisk));
});
