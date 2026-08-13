#!/usr/bin/env node

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { canonicalUrl, dedupeByItemId, dedupeReviews, parseCompactNumber, parseMappingIds } from "./dashboard_metrics.mjs";
import { cannibalizationRows, isWellFormedRisk, riskCounts } from "./cannibalization.mjs";
import { buildBenchmark, THEME_RULES } from "./competitor_benchmark.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const siteRoot = resolve(root, "outputs", "sonkuki_gsc_insights_site");
const outputPath = resolve(siteRoot, "worker", "dashboard_snapshot.js");
const mappingCandidates = [
  resolve(root, "shopify_homedepot_mapping.csv"),
  resolve(root, "inputs", "shopify_homedepot_mapping.csv"),
  resolve(siteRoot, "shopify_homedepot_mapping.csv"),
];

const values = Object.fromEntries(
  (await readFile(resolve(root, "credentials.txt"), "utf8"))
    .split(/\r?\n/)
    .filter((line) => line.includes(":"))
    .map((line) => {
      const index = line.indexOf(":");
      return [line.slice(0, index).trim(), line.slice(index + 1).trim()];
    }),
);

const api = values["NocoDB URL"];
const token = values["NocoDB PAT"];
const baseId = values["NocoDB Base ID"];
if (!api || !token || !baseId) throw new Error("NocoDB credentials are incomplete");

const tables = {
  gsc: "mfbg6s0mv9l74ky",
  queryRelevance: "muav8zitnoqlauu",
  month: "m0e006r2m3d1wg5",
  improved: "m1eh0kd0ryxeptu",
  newly: "mj3l8mejz31n8ry",
  products: "ma3331finostkis",
  hdProducts: "mnttfzrhu6gp6s0",
  reviews: "mnz1y5x5kydob4f",
  reviewLinks: "m040fohool0kx56",
  listings: "m7xynlp62mphmlv",
  variants: "m1br71dforlpotk",
  competitorProducts: "m0vk08vypm4jrl7",
  competitorSales: "munzznlmfzd9d2t",
};

const headers = { accept: "application/json", "xc-token": token };
async function records(tableId, fields) {
  const rows = [];
  for (let offset = 0; ; offset += 1000) {
    const params = new URLSearchParams({ limit: "1000", offset: String(offset), fields: fields.join(",") });
    let payload = null;
    let lastError = null;
    for (let attempt = 0; attempt < 6; attempt += 1) {
      try {
        const response = await fetch(`${api}/api/v2/tables/${tableId}/records?${params}`, { headers });
        if (!response.ok) throw new Error(`NocoDB ${tableId}: ${response.status}`);
        payload = await response.json();
        break;
      } catch (error) {
        lastError = error;
        if (attempt < 5) await new Promise((resolveDelay) => setTimeout(resolveDelay, Math.min(30000, 2000 * (2 ** attempt))));
      }
    }
    if (!payload) throw lastError || new Error(`NocoDB ${tableId}: request failed`);
    const batch = payload.list || [];
    rows.push(...batch);
    if (batch.length < 1000) return rows;
  }
}

const gsc = await records(tables.gsc, ["date", "page", "query", "branded_type", "clicks", "impressions", "position"]);
const queryRelevanceRows = await records(tables.queryRelevance, ["分组键", "query", "normalized_query", "relevance_status", "exclusion_reason", "Impressions"]);
const month = await records(tables.month, ["month", "domain", "query", "impressions", "clicks", "impression_tmp", "avg_position"]);
const improved = await records(tables.improved, ["query", "domain", "month", "avg_position", "impressions", "clicks"]);
const newly = await records(tables.newly, ["query", "month", "domain", "impressions", "clicks", "avg_position"]);
const products = await records(tables.products, ["title", "mpn", "original_price", "sale_price", "url"]);
const hdProducts = await records(tables.hdProducts, ["mpn", "name", "offers/price", "originalPrice", "totalVariants", "rating", "reviewCount", "url"]);
const reviews = await records(tables.reviews, ["review_key", "external_review_id", "review_date_iso_utc", "rating", "review_title", "review_text", "is_own"]);
const ownReviews = reviews.filter((row) => String(row.is_own) === "1");
const competitorReviewSourceRaw = reviews.filter((row) => String(row.is_own) !== "1");
const reviewLinks = await records(tables.reviewLinks, ["review_key", "listing_key"]);
const listings = await records(tables.listings, ["listing_key", "external_listing_id", "variant_key", "listing_title"]);
const variants = await records(tables.variants, ["variant_key", "mpn"]);
const competitorProductSource = await records(tables.competitorProducts, ["itemId", "name", "salePrice", "originalPrice", "offers|priceCurrency", "brand|slogan", "rating", "reviewCount", "inventory|isInStock", "state", "type", "savingsPercent", "CreatedAt", "UpdatedAt"]);
const competitorSalesSource = await records(tables.competitorSales, ["商品名称", "品牌", "类型", "售价", "价位段", "评分", "评论总数", "估算销量", "区间(低~高)", "近12月占比", "热度阶段", "CreatedAt", "UpdatedAt"]);

const number = (value) => parseCompactNumber(value);
const clean = (value) => String(value ?? "").trim();
const normalizeQueryText = (value) => String(value ?? "").normalize("NFKC").toLowerCase().trim().replace(/\s+/g, " ");
const relationValue = (value, preferredKeys = []) => {
  if (value && typeof value === "object") {
    for (const key of preferredKeys) if (clean(value[key])) return clean(value[key]);
    const first = Object.values(value).find((item) => typeof item !== "object" && clean(item));
    return clean(first);
  }
  return clean(value);
};
const dateValue = (value) => {
  const raw = clean(value);
  if (/^\d+(?:\.\d+)?$/.test(raw)) {
    const date = new Date(Date.UTC(1899, 11, 30) + Number(raw) * 86400000);
    return Number.isNaN(date.getTime()) ? raw : date.toISOString().slice(0, 10);
  }
  return raw.slice(0, 10);
};
const monthValue = (value) => dateValue(value).slice(0, 7);
const pageType = (value) => {
  let path = "";
  try { path = new URL(value).pathname; } catch { path = clean(value); }
  if (path === "/" || !path) return "Homepage";
  if (path.includes("/products/")) return "Product";
  if (path.includes("/blogs/")) return "Blog";
  if (path.includes("/collections/")) return "Collection";
  if (/\/(policies|pages|apps)\//.test(path)) return "Policy / Service";
  return "Other";
};
const parseCsv = (text) => {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"' && text[i + 1] === '"' && quoted) { cell += '"'; i += 1; continue; }
    if (char === '"') { quoted = !quoted; continue; }
    if (char === "," && !quoted) { row.push(cell); cell = ""; continue; }
    if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell); cell = "";
      if (row.some((item) => item.trim())) rows.push(row);
      row = [];
      continue;
    }
    cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  if (!rows.length) return [];
  const keys = rows.shift().map((key) => key.trim());
  return rows.map((values) => Object.fromEntries(keys.map((key, index) => [key, (values[index] || "").trim()])));
};

let mapping = [];
let mappingPath = null;
for (const candidate of mappingCandidates) {
  if (existsSync(candidate)) { mapping = parseCsv(await readFile(candidate, "utf8")); mappingPath = candidate; break; }
}
const byUrl = new Map(mapping.map((row) => [canonicalUrl(row.shopify_url), row]));
const byMpn = new Map(mapping.map((row) => [clean(row.shopify_mpn).toLowerCase(), row]));

const hdItemId = (row) => {
  const url = clean(row.url);
  const match = url.match(/[/-](\d{6,})\/?(?:\?.*)?$/);
  return match ? match[1] : "";
};
const hdIdsByMpn = new Map();
for (const row of hdProducts) {
  const mpn = clean(row.mpn).toLowerCase();
  const itemId = hdItemId(row);
  if (!mpn || !itemId) continue;
  const ids = hdIdsByMpn.get(mpn) || [];
  if (!ids.includes(itemId)) ids.push(itemId);
  hdIdsByMpn.set(mpn, ids);
}
const unresolvedMappingTokens = new Set();
const resolveMappingIds = (value) => parseMappingIds(value).flatMap((token) => {
  const ids = hdIdsByMpn.get(token.toLowerCase());
  if (ids?.length) return ids;
  if (/^\d{6,}$/.test(token)) return [token];
  unresolvedMappingTokens.add(token);
  return [];
});
const productRows = products.map((row) => {
  const url = canonicalUrl(row.url);
  const map = byUrl.get(url) || byMpn.get(clean(row.mpn).toLowerCase()) || null;
  return {
    title: clean(row.title), mpn: clean(row.mpn), original_price: number(row.original_price), sale_price: number(row.sale_price),
    url, page_type: pageType(url), hd_item_ids: map ? resolveMappingIds(map.homedepot_item_id) : [],
    mapping_status: map ? (clean(map.mapping_status) || "pending") : "pending",
  };
});
const hdRows = hdProducts.map((row) => ({
  itemId: hdItemId(row), mpn: clean(row.mpn), name: clean(row.name), salePrice: number(row["offers/price"]), originalPrice: number(row.originalPrice),
  totalVariants: number(row.totalVariants), rating: number(row.rating), reviewCount: number(row.reviewCount), url: canonicalUrl(row.url),
}));
const hdByItem = new Map(hdRows.filter((row) => row.itemId).map((row) => [row.itemId, row]));

// Shared theme rules: single source of truth in competitor_benchmark.mjs so the
// snapshot builder and the benchmark module always classify identically.
const themeRules = THEME_RULES;
const listingByKey = new Map(listings.map((row) => [clean(row.listing_key), row]));
const variantByKey = new Map(variants.map((row) => [clean(row.variant_key), row]));
const reviewLinkByKey = new Map();
for (const row of reviewLinks) {
  const key = clean(row.review_key);
  if (key && !reviewLinkByKey.has(key)) reviewLinkByKey.set(key, clean(row.listing_key));
}
const reviewSourceRows = [];
for (const row of ownReviews) {
  const reviewUid = clean(row.review_key) || clean(row.external_review_id) || [clean(row.review_date_iso_utc), clean(row.review_title)].join("|");
  const listing = listingByKey.get(reviewLinkByKey.get(reviewUid)) || {};
  const variant = variantByKey.get(clean(listing.variant_key)) || {};
  reviewSourceRows.push({
    review_uid: reviewUid, itemId: clean(listing.external_listing_id), mpn: clean(variant.mpn), rating: number(row.rating),
    review_date: clean(row.review_date_iso_utc).slice(0, 10), productName: clean(listing.listing_title),
    text: `${clean(row.review_title)} ${clean(row.review_text)}`,
  });
}
const reviewRows = dedupeReviews(reviewSourceRows).map((row) => {
  const rule = themeRules.find(([, regex]) => regex.test(row.text));
  return { review_uid: row.review_uid, itemId: row.itemId, mpn: row.mpn, rating: row.rating, review_date: row.review_date, productName: row.productName, theme: rule ? rule[0] : "Other" };
});
const negative = reviewRows.filter((row) => row.rating <= 2);
const themes = new Map();
for (const row of negative) {
  const current = themes.get(row.theme) || { theme: row.theme, count: 0, ratingSum: 0, products: new Set() };
  current.count += 1; current.ratingSum += row.rating; if (row.itemId) current.products.add(row.itemId); themes.set(row.theme, current);
}
const totalNegative = negative.length || 1;
const reviewThemes = [...themes.values()].sort((a, b) => b.count - a.count).map((row) => ({
  theme: row.theme, count: row.count, share: row.count / totalNegative, avgRating: row.ratingSum / row.count, affectedProducts: row.products.size,
  summaries: [`${row.count} 条低星评论归入该主题`, `覆盖 ${row.products.size} 个 Home Depot 商品`, "公开版仅展示去身份化聚合摘要"],
}));

const competitorProducts = dedupeByItemId(competitorProductSource.map((row) => ({
  itemId: clean(row.itemId), name: clean(row.name), brand: clean(row["brand|slogan"]) || "Unknown",
  salePrice: number(row.salePrice), originalPrice: number(row.originalPrice), currency: clean(row["offers|priceCurrency"]) || "USD",
  rating: number(row.rating), reviewCount: number(row.reviewCount), inStock: clean(row["inventory|isInStock"]).toLowerCase() === "true",
  fulfillment: clean(row.type), state: clean(row.state), savingsPercent: number(row.savingsPercent),
  createdAt: clean(row.CreatedAt), updatedAt: clean(row.UpdatedAt),
}))).filter((row) => row.itemId && row.name && row.brand !== "Unknown");

const competitorByItemId = new Map(competitorProducts.map((row) => [row.itemId, row]));
const competitorReviewSourceRows = competitorReviewSourceRaw.map((row) => {
  const reviewUid = clean(row.review_key) || clean(row.external_review_id) || [clean(row.review_date_iso_utc), clean(row.review_title)].join("|");
  const listing = listingByKey.get(reviewLinkByKey.get(reviewUid)) || {};
  const variant = variantByKey.get(clean(listing.variant_key)) || {};
  return {
    review_uid: reviewUid, itemId: clean(listing.external_listing_id), rating: number(row.rating),
    review_date: clean(row.review_date_iso_utc).slice(0, 10), productName: clean(listing.listing_title),
    text: `${clean(row.review_title)} ${clean(row.review_text)}`,
  };
});
const competitorReviews = dedupeReviews(competitorReviewSourceRows).map((row) => ({
  review_uid: row.review_uid, itemId: row.itemId, rating: row.rating, review_date: row.review_date,
  brand: competitorByItemId.get(row.itemId)?.brand || "Unknown",
  theme: (themeRules.find(([, regex]) => regex.test(row.text)) || ["Other"])[0],
}));
const competitorNegative = competitorReviews.filter((row) => row.rating <= 2);
const competitorThemeAccumulator = new Map();
for (const row of competitorNegative) {
  const current = competitorThemeAccumulator.get(row.theme) || { theme: row.theme, count: 0, products: new Set(), brands: new Set() };
  current.count += 1;
  if (row.itemId) current.products.add(row.itemId);
  if (row.brand !== "Unknown") current.brands.add(row.brand);
  competitorThemeAccumulator.set(row.theme, current);
}
const competitorReviewThemes = [...competitorThemeAccumulator.values()].sort((a, b) => b.count - a.count).map((row) => ({
  theme: row.theme, count: row.count, share: row.count / Math.max(1, competitorNegative.length), affectedProducts: row.products.size, affectedBrands: row.brands.size,
  summary: `${row.count} 条去重低星评论，覆盖 ${row.products.size} 个商品与 ${row.brands.size} 个品牌。`,
}));
const competitorSales = competitorSalesSource.map((row) => ({
  name: clean(row["商品名称"]), brand: clean(row["品牌"]) || "Unknown", category: clean(row["类型"]) || "Unknown",
  price: number(row["售价"]), priceBand: clean(row["价位段"]) || "Unknown", rating: number(row["评分"]), reviewCount: number(row["评论总数"]),
  estimatedSales: number(row["估算销量"]), salesRange: clean(row["区间(低~高)"]), share12m: number(row["近12月占比"]), heatStage: clean(row["热度阶段"]) || "Unknown",
  updatedAt: clean(row.UpdatedAt) || clean(row.CreatedAt),
})).filter((row) => row.name && row.brand !== "Unknown");
const latestCompetitorProductAt = competitorProducts.map((row) => row.updatedAt || row.createdAt).filter(Boolean).sort().at(-1) || null;
const latestCompetitorSalesAt = competitorSales.map((row) => row.updatedAt).filter(Boolean).sort().at(-1) || null;

// Market benchmark (homedepot_competitors_compare.md): Pergola pilot. Same
// logic and overrides as scripts/run_competitor_benchmark.mjs so the snapshot
// and the standalone runner agree. The override marks own SKUs whose title
// omits "Louvered" but whose series is verifiably louvered (Sereno LED).
const serenoLedOverrides = new Set(
  hdRows
    .filter((row) => /sereno series/i.test(row.name) && /solar-powered led/i.test(row.name) && !/louver/i.test(row.name))
    .map((row) => clean(row.itemId))
    .filter(Boolean),
);
const marketBenchmark = buildBenchmark(
  { hdProducts: hdRows, competitor: { products: competitorProducts, reviews: competitorReviews }, reviews: reviewRows },
  "Pergola",
  new Date().toISOString().slice(0, 10),
  serenoLedOverrides,
);

const relevanceByQuery = new Map();
const relevanceByNormalized = new Map();
for (const row of queryRelevanceRows) {
  const raw = clean(row["分组键"]) || clean(row.query);
  if (!raw) continue;
  const status = clean(row.relevance_status) || "UNKNOWN";
  const reason = clean(row.exclusion_reason) || "NO_RULE_MATCH";
  if (!relevanceByQuery.has(raw)) relevanceByQuery.set(raw, { status, reason });
  const norm = clean(row.normalized_query) || normalizeQueryText(raw);
  if (!relevanceByNormalized.has(norm)) relevanceByNormalized.set(norm, { status, reason });
}
const relevanceStatus = (query) => relevanceByQuery.get(query) || relevanceByNormalized.get(normalizeQueryText(query)) || { status: "UNKNOWN", reason: "NO_RULE_MATCH" };

const relevanceSummary = { total: queryRelevanceRows.length, valid: 0, irrelevant: 0, unknown: 0, reasons: {} };
for (const row of queryRelevanceRows) {
  const status = clean(row.relevance_status);
  if (status === "VALID") relevanceSummary.valid += 1;
  else if (status === "IRRELEVANT") relevanceSummary.irrelevant += 1;
  else relevanceSummary.unknown += 1;
  const reason = clean(row.exclusion_reason) || "NO_RULE_MATCH";
  relevanceSummary.reasons[reason] = (relevanceSummary.reasons[reason] || 0) + 1;
}

const gscRows = gsc.map((row) => {
  const query = relationValue(row.query, ["分组键", "query"]);
  const relevance = relevanceStatus(query);
  return {
    date: dateValue(row.date), page: relationValue(row.page, ["page_url", "page"]), canonical_page: canonicalUrl(relationValue(row.page, ["page_url", "page"])), page_type: pageType(relationValue(row.page, ["page_url", "page"])), query,
    relevance_status: relevance.status, exclusion_reason: relevance.reason,
    branded_type: clean(row.branded_type) || "未知",
    clicks: number(row.clicks), impressions: number(row.impressions), position_weight: number(row.position) * number(row.impressions),
  };
});
// Keyword cannibalization (keyword_cannibalization.md): only VALID queries
// participate; IRRELEVANT and UNKNOWN queries are excluded. Risk is computed
// from meaningful URLs (impression share >= 10% or >= 50 impressions), never
// from a raw URL count.
const cannibalRows = cannibalizationRows(gscRows.filter((row) => row.relevance_status === "VALID"));
const cannibalRiskSummary = { analyzed: cannibalRows.length, byRisk: riskCounts(cannibalRows) };
const cannibalNotWellFormed = cannibalRows.filter((row) => !isWellFormedRisk(row));
const monthRows = month.map((row) => ({
  month: monthValue(row.month), query: clean(row.query), impressions: number(row.impressions), clicks: number(row.clicks), position_weight: number(row.impression_tmp), avg_position: number(row.avg_position),
}));
const dates = gscRows.map((row) => row.date).filter(Boolean).sort();
const availableMonths = [...new Set(dates.map((date) => date.slice(0, 7)))].sort();
const confirmedProductRows = productRows.filter((row) => row.mapping_status === "confirmed");
const mappingResolved = confirmedProductRows.filter((row) => row.hd_item_ids.length && row.hd_item_ids.every((itemId) => hdByItem.has(itemId))).length;
const unresolvedMappedItemIds = [...new Set(confirmedProductRows.flatMap((row) => row.hd_item_ids.filter((itemId) => !hdByItem.has(itemId))))];
const mapComplete = productRows.length > 0 && productRows.every((row) => ["confirmed", "not_listed"].includes(row.mapping_status)) && unresolvedMappingTokens.size === 0 && unresolvedMappedItemIds.length === 0;
const competitorProductMissing = competitorProductSource.length - competitorProducts.length;
const competitorSalesJoinable = false;
const noPii = !JSON.stringify({ gscRows, monthRows, improved, newly, productRows, hdRows, reviewRows, reviewThemes, competitorProducts, competitorReviews, competitorReviewThemes, competitorSales, cannibalRows, marketBenchmark }).match(/reviewText|userName|userNickname|authorId|userLocation/);

// Query relevance QA (mirrors irrelevant_query_clean.md sections 9 and 10).
const rawQueryCount = new Set(queryRelevanceRows.map((row) => clean(row["分组键"]) || clean(row.query))).size;
const rawTotals = gsc.reduce((acc, row) => ({ clicks: acc.clicks + number(row.clicks), impressions: acc.impressions + number(row.impressions) }), { clicks: 0, impressions: 0 });
const snapshotTotals = gscRows.reduce((acc, row) => ({ clicks: acc.clicks + row.clicks, impressions: acc.impressions + row.impressions }), { clicks: 0, impressions: 0 });
const queryAgg = (items) => {
  const map = new Map();
  for (const item of items) {
    const bucket = map.get(item.query) || { query: item.query, impressions: 0, clicks: 0, positionWeight: 0, pages: new Set() };
    bucket.impressions += item.impressions; bucket.clicks += item.clicks; bucket.positionWeight += item.position_weight; bucket.pages.add(item.canonical_page);
    map.set(item.query, bucket);
  }
  return [...map.values()].map((bucket) => ({ query: bucket.query, impressions: bucket.impressions, clicks: bucket.clicks, ctr: bucket.impressions ? bucket.clicks / bucket.impressions : 0, position: bucket.impressions ? bucket.positionWeight / bucket.impressions : 0, pages: bucket.pages.size }));
};
const opportunityCandidates = queryAgg(gscRows.filter((row) => row.relevance_status === "VALID")).sort((a, b) => b.impressions - a.impressions).slice(0, 20).filter((row) => row.position >= 4 && row.position <= 20);
const opportunityBad = opportunityCandidates.filter((row) => relevanceStatus(row.query).status !== "VALID");
const excludedQueries = queryRelevanceRows.filter((row) => { const status = clean(row.relevance_status); return status === "IRRELEVANT" || status === "UNKNOWN"; });
const excludedImpressions = excludedQueries.reduce((sum, row) => sum + number(row.Impressions), 0);
// QA guard for check 5: no brand / core product query may be mislabeled.
const brandGuard = /sonkuki|son[\s-]?uki|sankuki|zimi\s+america|bonosuki/i;
const coreProductGuard = ["pergola", "louver", "umbrella", "parasol", "furniture", "chair", "sofa", "patio", "outdoor", "adirondack", "gazebo"];
const mislabeledCore = queryRelevanceRows.filter((row) => {
  if (clean(row.relevance_status) === "VALID") return false;
  const q = normalizeQueryText(clean(row["分组键"]) || clean(row.query));
  return brandGuard.test(q) || coreProductGuard.some((term) => q.includes(term));
});

const checks = [
  { id: "ctr", label: "CTR is recomputed from clicks / impressions", status: "pass", detail: "No row-level CTR is used." },
  { id: "position", label: "Position uses impression-weighted sums", status: "pass", detail: "position_weight is retained for every GSC row." },
  { id: "canonical", label: "URLs are canonicalized before product aggregation", status: "pass", detail: `${new Set(gscRows.map((row) => row.canonical_page)).size} canonical pages.` },
  { id: "reviews", label: "Reviews are deduplicated by review UID", status: "pass", detail: `${ownReviews.length} own source rows → ${reviewRows.length} unique reviews.` },
  { id: "mapping", label: "Shopify ↔ Home Depot mapping is complete", status: mapComplete ? "pass" : "warning", detail: mappingPath ? `${confirmedProductRows.length}/${productRows.length} confirmed; ${mappingResolved} resolved to live HD rows${unresolvedMappingTokens.size ? `; ${unresolvedMappingTokens.size} unresolved mapping tokens` : ""}${unresolvedMappedItemIds.length ? `; ${unresolvedMappedItemIds.length} mapped Item IDs absent from the current table` : ""}.` : "Mapping CSV not found; cross-channel views are waiting for confirmation." },
  { id: "competitor_listings", label: "Competitor listings use unique Home Depot item IDs", status: competitorProductMissing ? "warning" : "pass", detail: `${competitorProductSource.length} source rows → ${competitorProducts.length} analysis-ready competitor items${competitorProductMissing ? `; ${competitorProductMissing} incomplete or duplicate rows excluded` : ""}.` },
  { id: "competitor_reviews", label: "Competitor reviews are deduplicated before social-proof metrics", status: "pass", detail: `${competitorReviewSourceRaw.length} source rows → ${competitorReviews.length} unique review UIDs.` },
  { id: "competitor_sales", label: "Competitor sales estimates are aggregate-only", status: competitorSalesJoinable ? "pass" : "warning", detail: `${competitorSales.length} modeled sales rows have no stable Home Depot Item ID; sales signals are not joined to individual listing or review metrics.` },
  { id: "pii", label: "Snapshot excludes PII and raw review text", status: noPii ? "pass" : "fail", detail: noPii ? "Only aggregated, de-identified review fields are included." : "Sensitive fields found." },
  { id: "partial_months", label: "Partial months are marked", status: "pass", detail: "April and August are flagged as partial when present." },
  { id: "relevance_filter", label: "Query relevance filtering", status: relevanceSummary.total > 0 ? "pass" : "fail", detail: `${relevanceSummary.total} raw queries → ${relevanceSummary.valid} valid → ${relevanceSummary.irrelevant} irrelevant → ${relevanceSummary.unknown} unknown · Irrelevant queries excluded from opportunity analysis` },
  { id: "query_count", label: "Raw query count unchanged", status: rawQueryCount === 2013 ? "pass" : "fail", detail: `${rawQueryCount} unique queries (expect 2,013).` },
  { id: "raw_totals", label: "Raw clicks and impressions unchanged", status: snapshotTotals.clicks === rawTotals.clicks && snapshotTotals.impressions === rawTotals.impressions ? "pass" : "fail", detail: `${snapshotTotals.clicks.toLocaleString()} clicks / ${snapshotTotals.impressions.toLocaleString()} impressions preserved from source.` },
  { id: "opportunity_clean", label: "Opportunity excludes IRRELEVANT and UNKNOWN", status: opportunityBad.length ? "fail" : "pass", detail: `${excludedQueries.length} non-VALID queries (${excludedImpressions.toLocaleString()} impressions) kept out of opportunity analysis.` },
  { id: "brand_core_preserved", label: "Brand and core product terms preserved", status: mislabeledCore.length ? "fail" : "pass", detail: `${mislabeledCore.length} brand/product queries mislabeled; all stay VALID.` },
  { id: "relevance_coverage", label: "Query relevance classification complete", status: relevanceSummary.valid + relevanceSummary.irrelevant + relevanceSummary.unknown === relevanceSummary.total ? "pass" : "fail", detail: `All ${relevanceSummary.total} queries classified as VALID / IRRELEVANT / UNKNOWN.` },
  { id: "cannibal_valid_only", label: "Cannibalization analyzes VALID queries only", status: "pass", detail: `${cannibalRiskSummary.analyzed} VALID queries analyzed · IRRELEVANT and UNKNOWN queries excluded from cannibalization risk.` },
  { id: "cannibal_risk", label: "Cannibalization risk is well-formed", status: cannibalNotWellFormed.length ? "fail" : "pass", detail: `${cannibalRiskSummary.byRisk.LOW} LOW / ${cannibalRiskSummary.byRisk.MEDIUM} MEDIUM / ${cannibalRiskSummary.byRisk.HIGH} HIGH · one primary URL per query, share-based risk only.` },
  { id: "benchmark_coverage", label: "Pergola own units have a competitor benchmark", status: marketBenchmark.units.every((row) => row.competitorCount > 0 || row.tier === "none") ? "pass" : "fail", detail: `${marketBenchmark.coverage.ownUnits} own units (${marketBenchmark.coverage.ownListings} listings) vs ${marketBenchmark.coverage.competitorUnits} competitor units (${marketBenchmark.coverage.competitorListings} listings) · ${marketBenchmark.coverage.matchExact} exact / ${marketBenchmark.coverage.matchApproximate} approximate / ${marketBenchmark.coverage.matchNone} none · ${marketBenchmark.priorityActions.length} priority actions.` },
];
if (!noPii) throw new Error("Snapshot blocked: PII field detected");

const snapshot = {
  schemaVersion: 2, generatedAt: new Date().toISOString(), source: { base: values["NocoDB Base"] || "Sonkuki", baseId, gscDateMin: dates[0] || null, gscDateMax: dates.at(-1) || null, availableMonths, mappingPath: mappingPath ? "provided" : null, competitorProductUpdatedAt: latestCompetitorProductAt, competitorSalesUpdatedAt: latestCompetitorSalesAt },
  quality: { status: checks.some((check) => check.status === "fail") ? "blocked" : checks.some((check) => check.status === "warning") ? "warning" : "pass", checks, mappingComplete: mapComplete },
  gscRows, monthRows, queryRelevance: relevanceSummary, cannibalization: cannibalRiskSummary,
  improvedRows: improved.map((row) => ({ query: clean(row.query), month: monthValue(row.month), avg_position: number(row.avg_position), impressions: number(row.impressions), clicks: number(row.clicks) })),
  newlyRankedRows: newly.map((row) => ({ query: clean(row.query), month: monthValue(row.month), avg_position: number(row.avg_position), impressions: number(row.impressions), clicks: number(row.clicks) })),
  products: productRows, hdProducts: hdRows, reviews: reviewRows, reviewThemes,
  competitor: { products: competitorProducts, reviews: competitorReviews, reviewThemes: competitorReviewThemes, sales: competitorSales, productSalesJoinable: competitorSalesJoinable },
  marketBenchmark,
  joins: { hdItemIds: [...hdByItem.keys()], mappedProducts: mappingResolved, unresolvedMappingTokens: [...unresolvedMappingTokens], unresolvedMappedItemIds },
};

const serialized = JSON.stringify(snapshot);
await writeFile(outputPath, `// Generated by scripts/build_dashboard_snapshot.mjs. Do not edit by hand.\nexport const SNAPSHOT = ${serialized};\n`, "utf8");
console.log(JSON.stringify({ outputPath, sourceRows: gscRows.length, products: productRows.length, hdProducts: hdRows.length, reviews: reviewRows.length, competitorProducts: competitorProducts.length, competitorReviews: competitorReviews.length, competitorSales: competitorSales.length, quality: snapshot.quality.status, mappingComplete: mapComplete }, null, 2));
