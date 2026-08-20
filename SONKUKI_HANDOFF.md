# SONKUKI dashboard sync hand-off

Last successful snapshot refresh: 2026-08-13 (rebuilt live after NocoDB recovery).
Latest change: query relevance cleaning shipped (see Query relevance cleaning below) — GSC queries are tagged VALID / IRRELEVANT / UNKNOWN and only VALID enters Keyword Opportunity. Deployed temporarily to Vercel at https://sonkuki-gsc-insights.vercel.app — **Vercel production redeployed 2026-08-13 with the new 市场对标 Benchmark page (marketBenchmark live) and verified** (snapshot 7.55 MB, generatedAt 2026-08-13T08:47Z, benchmark_coverage pass). Sites version 9 is saved but not deployed because the workspace is out of credits and the `openai` deployment CLI is not available in this environment.

## Home Depot market benchmark (new, 2026-08-13)

Spec: `homedepot_competitors_compare.md`. Own-vs-competitor market analysis, Pergola pilot. Pure module `scripts/competitor_benchmark.mjs` + runner `scripts/run_competitor_benchmark.mjs`.

- Run (offline, no NocoDB needed): `node scripts/run_competitor_benchmark.mjs [category]`. It reads `outputs/sonkuki_gsc_insights_site/public/snapshot.json`, writes `outputs/competitor_benchmark_{unified,groups,units,skus,coverage,actions,}_<date>.{csv,json}`, and augments `worker/dashboard_snapshot.js` + re-exports `public/`. The snapshot builder computes `marketBenchmark` on normal refreshes (same logic/overrides) and adds a `benchmark_coverage` quality check.
- **Comparison basis (optimized):** own and competitor both use **Product Units**. Own unit = variant SKUs sharing one group (23 SKUs → 8 units). Competitor unit = one (brand, group) pair (299 listings → 191 units); unit price = listing median, rating = review-weighted, reviews = sum. Listings only describe market coverage. Grouping: Category × Size × Material, Louvered = core function. Tiers: exact → tolerance(±1ft) → size → material → none; match quality maps to 高/中/低置信度 / 无可比.
- **Actions (optimized):** one primary action per unit with product group / problem / evidence / suggestion. Rules: no reviews → 建立社会证明 (priority); price ≥ +10% above median → 检查价格溢价; rating gap < 0.1 treated as tied; low-star share gap > 5pp drives 改善安装体验 / 改善材料或耐用性 (Other theme → 强化产品卖点, never a product action); reviews < 50% of median → 增加评论积累. Low-confidence (size/material tier) appends a manual-check hint.
- **VOC (optimized):** own low-star < MIN_VOC_SAMPLE(10) → `sampleInsufficient`, no above/below-market conclusion, shows "样本不足，暂不判断市场差异". Diffs reported in percentage points (gapPp). Current Pergola VOC is insufficient (own 2 vs comp 55 low-star).
- **Dashboard "市场对标 Benchmark" page:** Benchmark Coverage (own 8 units/23 listings, comp 191 units/299 listings, 5 exact / 3 approx / 0 none, Scope + snapshot date), Product Benchmark unit table (group label first column, price % diff, `—` for no-rating), Priority Actions, VOC Comparison, filters Category/Size/Material/Competitor Brand/Match Quality.
- Tests: `tests/competitor_benchmark.test.mjs` (26 tests, wired into site `npm test`).

## Current state

- Public site (Vercel, temporary): https://sonkuki-gsc-insights.vercel.app
- Sites deployment (pending credits): https://sonkuki-gsc-insights.brandrap-5927.chatgpt.site/
- Site project: `outputs/sonkuki_gsc_insights_site`
- Snapshot GSC range: 2026-04-22 through 2026-08-08
- Shopify ↔ Home Depot: 30/31 confirmed products resolved to live HD rows
- Current snapshot counts (2026-08-20 audit): 12,389 GSC rows, 31 sonkuki_products, 9,762 reviews, 13,401 review_listing_links, 669 listings, 698 variants, 676 products, 71 brands
- Query relevance: 2,013 queries → 1,838 VALID / 7 IRRELEVANT / 168 UNKNOWN; only VALID feeds Keyword Opportunity
- Schema: 14 live NocoDB tables on HDV1 analytic chain + GSC (flat ingest tables homedepot_products / competitor_products / competitor_sales removed 2026-08). See `docs/schema_architecture.md`.

## Refresh

Run from the repository root:

```bash
# 1. Reclassify queries (re-run whenever GSC data changes)
python3 scripts/classify_query_relevance.py

# 2. Rebuild snapshot + site
node scripts/build_dashboard_snapshot.mjs
cd outputs/sonkuki_gsc_insights_site
npm run build
npm run validate
npm test

# 3. Publish (temporary host)
vercel deploy --prod
```

The refresh script uses the current normalized NocoDB tables. It reads credentials from `credentials.txt`; never commit or expose that file, tokens, raw review text, reviewer names, or locations.

## Query relevance cleaning

Spec: `irrelevant_query_clean.md`. Every query in `gsc_keyword_all_time` is tagged with `relevance_status` (VALID / IRRELEVANT / UNKNOWN) and `exclusion_reason`; only VALID rows form the Clean Query Dataset that feeds Keyword Opportunity. Raw GSC totals and the legacy `is_noise` column are untouched.

- Rules (scripts/query_relevance.py): Rule 4 external-domain + customer-service terms → IRRELEVANT; Rule 1 SONKUKI brand terms → VALID; Rule 2 core product terms → VALID; Rule 3 known competitor / retailer → VALID; no match → UNKNOWN.
- Sync: `scripts/classify_query_relevance.py` writes `query`, `normalized_query`, `relevance_status`, `exclusion_reason` back to NocoDB and exports `outputs/query_relevance_<date>.csv`, `outputs/clean_query_dataset_<date>.csv`, `outputs/query_relevance_qa_<date>.json`.
- Dashboard: the snapshot attaches `relevance_status` to every GSC row; the Opportunity page and the Product SEO action panel use VALID queries only, and the Executive page keeps raw totals. QA checks for relevance are in `scripts/build_dashboard_snapshot.mjs`.
- Tests: `tests/test_query_relevance.py` (run `python3 -m unittest discover -s tests`).

## Current NocoDB table mapping (14 live tables)

**HDV1 analytic chain**

- `reviews`: `mnz1y5x5kydob4f`
- `review_listing_links`: `m040fohool0kx56`
- `product_listings`: `m7xynlp62mphmlv`
- `product_variants`: `m1br71dforlpotk`
- `products`: `m2w1cuciam30ltz`
- `brands`: `m7ue920zwzocr6t`
- `listing_snapshots`: `mq2abnm4fqtz1f5`

**Catalog**

- `sonkuki_products`: `ma3331finostkis`

**GSC**

- `gsc_raw`: `mfbg6s0mv9l74ky`
- `gsc_keyword_all_time`: `muav8zitnoqlauu` (query dimension; carries `query`, `normalized_query`, `relevance_status`, `exclusion_reason`)
- `gsc_page_all_time`: `m0fl1tcxyopz1s3`
- `gsc_keyword_month`: `m0e006r2m3d1wg5`
- `gsc_keyword_improved`: `m1eh0kd0ryxeptu`
- `gsc_keyword_newly_ranked`: `mj3l8mejz31n8ry`

**Removed 2026-08 (do not reference):** `homedepot_products` (`mnttfzrhu6gp6s0`), `competitor_products` (`m0vk08vypm4jrl7`), `competitor_sales` (`munzznlmfzd9d2t`), `raw_listing_snapshots` (`mzi7pcyvcg0865m`), `ingestion_runs`, `source_registry`.

If NocoDB table IDs change again, inspect `/api/v1/db/meta/projects/{base_id}/tables` and update `scripts/build_dashboard_snapshot.mjs` (and `scripts/orphan_audit.py` TABLE constants) before refreshing. Confirm page/query relation fields are normalized (`page.page_url`, `query.分组键`) and preserve impression-weighted position calculations.

## Publish

- **Vercel (current, temporary)**: project `sonkuki-gsc-insights` is linked in `outputs/sonkuki_gsc_insights_site/.vercel/project.json`. Deploy with `vercel deploy --prod` from that directory. `vercel.json` builds via `node scripts/export_vercel_static.mjs`, serves `public/`, and rewrites `/api/snapshot` → `snapshot.json`, `/api/manifest` → `manifest.json`. Live at https://sonkuki-gsc-insights.vercel.app
- `.vercelignore` excludes `dist/` and `public/` (both are regenerated by the remote build), so uploads stay small.
- **Sites (pending credits)**: use the existing Sites project in `outputs/sonkuki_gsc_insights_site/.openai/hosting.json`. The latest validated source is commit `d243d52ea6bbfd6c472249d501d22921735a5099`; Sites version 9 is saved and ready to deploy. Retry deployment after the workspace credits are refilled. Do not publish an unvalidated snapshot.
