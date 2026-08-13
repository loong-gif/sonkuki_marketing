import test from "node:test";
import assert from "node:assert/strict";
import { canonicalUrl, ctrFromTotals, dedupeByItemId, dedupeReviews, normalizeEntityLabel, parseCompactNumber, parseMappingIds, potentialClicks, weightedPosition } from "../scripts/dashboard_metrics.mjs";
import { coverageCopy, parseFilters, productIdentity, serializeFilters, shortPageLabel, topN } from "../scripts/dashboard_ui.mjs";
import { SNAPSHOT } from "../outputs/sonkuki_gsc_insights_site/worker/dashboard_snapshot.js";
import worker from "../outputs/sonkuki_gsc_insights_site/worker/index.js";

test("canonical URL removes query strings and trailing slash", () => {
  assert.equal(canonicalUrl("https://sonkuki.com/products/demo?variant=123&utm_source=x#top"), "https://sonkuki.com/products/demo");
});

test("mapping parser supports one Shopify SKU to many HD item IDs", () => {
  assert.deepEqual(parseMappingIds("111;222|333"), ["111", "222", "333"]);
});

test("CTR and weighted position use aggregate denominators", () => {
  assert.equal(ctrFromTotals(25, 1000), 0.025);
  assert.equal(weightedPosition([{ impressions: 100, position_weight: 500 }, { impressions: 50, position_weight: 100 }]), 4);
});

test("review UID dedupe keeps one row per syndicated source review", () => {
  const rows = dedupeReviews([{ review_uid: "r1", itemId: "200" }, { review_uid: "r1", itemId: "100" }, { review_uid: "r2", itemId: "300" }]);
  assert.equal(rows.length, 2);
  assert.equal(rows.find((row) => row.review_uid === "r1").itemId, "100");
});

test("potential clicks is bounded at zero", () => {
  assert.equal(potentialClicks({ impressions: 1000, ctr: 0.01, benchmarkCtr: 0.04 }), 30);
  assert.equal(potentialClicks({ impressions: 1000, ctr: 0.05, benchmarkCtr: 0.04 }), 0);
});

test("competitor helpers normalize brands, compact values, and duplicate item snapshots", () => {
  assert.equal(normalizeEntityLabel("  COVERED  OUTDOOR  "), "covered outdoor");
  assert.equal(parseCompactNumber("$1,125.50"), 1125.5);
  assert.equal(parseCompactNumber("10.6k"), 10600);
  assert.deepEqual(
    dedupeByItemId([
      { itemId: "100", updatedAt: "2026-08-11T00:00:00Z", salePrice: 100 },
      { itemId: "100", updatedAt: "2026-08-12T00:00:00Z", salePrice: 120 },
      { itemId: "200", updatedAt: "2026-08-11T00:00:00Z", salePrice: 200 },
    ]),
    [
      { itemId: "100", updatedAt: "2026-08-12T00:00:00Z", salePrice: 120 },
      { itemId: "200", updatedAt: "2026-08-11T00:00:00Z", salePrice: 200 },
    ],
  );
});

test("competitor snapshot is deduplicated and contains no source review content", () => {
  assert.equal(new Set(SNAPSHOT.competitor.products.map((row) => row.itemId)).size, SNAPSHOT.competitor.products.length);
  assert.equal(new Set(SNAPSHOT.competitor.reviews.map((row) => row.review_uid)).size, SNAPSHOT.competitor.reviews.length);
  assert.equal(SNAPSHOT.competitor.productSalesJoinable, false);
  assert.equal(JSON.stringify(SNAPSHOT.competitor).includes("reviewText"), false);
  assert.equal(JSON.stringify(SNAPSHOT.competitor).includes("userName"), false);
});

test("UI helpers preserve readable identities, chart limits, quality copy, and shared filter state", () => {
  assert.equal(shortPageLabel("https://sonkuki.com/products/a-really-long-product-path?variant=1"), "/products/a-really-long-product-pa…");
  assert.deepEqual(productIdentity({ title: "Pergola", mpn: "SML-12X20" }), { title: "Pergola", subtitle: "SML-12X20" });
  assert.deepEqual(topN([{ label: "A", value: 2 }, { label: "B", value: 5 }, { label: "C", value: 1 }], 2).map((row) => row.label), ["B", "A"]);
  assert.equal(coverageCopy({ status: "warning", checks: [{ status: "warning" }, { status: "pass" }] }).tone, "warning");
  const state = { page: "product", from: "2026-08-01", to: "", brand: "all", pageType: "Product", query: "pergola", product: "all", competitorBrand: "all" };
  assert.deepEqual(parseFilters(serializeFilters(state)), state);
});

test("snapshot is normalized, token-free, and confirms the resolved product mapping", () => {
  assert.equal(SNAPSHOT.source.gscDateMin, "2026-04-22");
  assert.equal(SNAPSHOT.source.gscDateMax, "2026-08-08");
  assert.ok(SNAPSHOT.gscRows.length > 10000);
  assert.ok(SNAPSHOT.gscRows.every((row) => !/[?&]variant=|utm_/i.test(row.canonical_page)));
  assert.equal(new Set(SNAPSHOT.reviews.map((row) => row.review_uid)).size, SNAPSHOT.reviews.length);
  assert.equal(JSON.stringify(SNAPSHOT).includes("reviewText"), false);
  assert.equal(SNAPSHOT.quality.mappingComplete, true);
  assert.equal(SNAPSHOT.joins.mappedProducts, 30);
  assert.deepEqual(SNAPSHOT.joins.unresolvedMappedItemIds, []);
  assert.equal(SNAPSHOT.competitor.products.length, 378);
  assert.equal(SNAPSHOT.competitor.reviews.length, 2007);
  assert.equal(SNAPSHOT.competitor.sales.length, 78);
  assert.equal(JSON.stringify(SNAPSHOT.competitor).match(/userName|reviewText/), null);
});

test("SEO filters are scoped to the SEO page and market filters to the market page", async () => {
  const html = await (await worker.fetch(new Request("https://sonkuki.local/"))).text();
  const globalFilter = html.match(/<section class="filter-panel" aria-label="Dashboard filters">([\s\S]*?)<\/section>/)?.[1] || "";
  const searchPage = html.match(/<section class="page" data-page-view="search">([\s\S]*?)<\/section>\s*<section class="page" data-page-view="market">/)?.[1] || "";
  const marketStart = html.indexOf('<section class="page" data-page-view="market">');
  const methodStart = html.indexOf('<section class="page" data-page-view="method">');
  const marketPage = marketStart >= 0 && methodStart > marketStart ? html.slice(marketStart, methodStart) : "";

  assert.equal(html.includes('aria-label="Dashboard filters"'), false);
  assert.equal(html.includes('id="copy-link"'), false);
  assert.equal(searchPage.includes('id="query-filter"'), true);
  assert.equal(searchPage.includes('id="date-from"'), true);
  assert.equal(searchPage.includes('id="page-filter"'), true);
  const competitorFilterAt = html.indexOf('id="competitor-brand-filter"');
  assert.equal(competitorFilterAt > marketStart && competitorFilterAt < methodStart, true);
});
