# Sonkuki 数据库架构说明 (双轨模型)

> 更新:2026-08-13。Base: Sonkuki (p447va1t8jqqjty),20 张表,全部 snake_case 命名。
> 决策:保留"采集层 + 关联分析层"双轨 (Option A),本文档定义各自职责,避免误用。

## 总体结构

```
┌─────────────────────────────────────────────────────────────┐
│  采集层 (扁平表) — 抓取原样入库,看板唯一数据源                │
│  sonkuki_products / homedepot_products / competitor_products │
│  competitor_sales / gsc_*                                   │
├─────────────────────────────────────────────────────────────┤
│  关联分析层 (规范化链) — 评论与其商品归属的唯一来源            │
│  brands → products → product_variants → product_listings →  │
│  review_listing_links → reviews                              │
│  listing_snapshots / raw_listing_snapshots (快照归档)        │
│  ingestion_runs / source_registry (管线元数据)               │
└─────────────────────────────────────────────────────────────┘
```

## 表清单 (2026-08-13 重命名后)

| 表 (title) | 旧名 | 行数 | 职责 | 消费者 |
|---|---|---|---|---|
| sonkuki_products | page_product | 31 | sonkuki.com 官网目录 | 看板 Product SEO 页 |
| homedepot_products | homedepot_product | 267 | 自家商品在 HD 的 listing | 看板 Marketplace 页 |
| competitor_products | competitor_product | 415 | 竞品商品 (含 93 个有评论的) | 看板 Competitors 页 |
| competitor_sales | competitor_product_sale | 78 | 竞品销量估算 (无法 join,仅聚合) | 看板 Competitors 页 |
| gsc_raw | gsc_data_raw | 12389 | GSC 唯一明细源 (含 branded_type 等分析列) | 看板 GSC 各页 |
| gsc_keyword_all_time | gsc_keyword_all-time | 2013 | GSC 关键词维度汇总 (被 gsc_raw 的 FK 引用) | 看板 GSC 各页 |
| gsc_page_all_time | gsc_page_all-time | 242 | GSC 页面维度汇总 (被 gsc_raw 的 FK 引用) | 看板 GSC 各页 |
| gsc_keyword_month | 不变 | 3101 | GSC 派生报表视图 | 报表/BI |
| gsc_keyword_improved | 不变 | 88 | GSC 派生报表视图 | 报表/BI |
| gsc_keyword_newly_ranked | 不变 | 116 | GSC 派生报表视图 | 报表/BI |
| reviews | HDV1_Customer_Reviews | 6996 | **唯一评论源** (own=4989, competitor=2007,is_own 标记) | 评论分析/看板 |
| review_listing_links | HDV1_Review_Listing_Links | 7840 | 评论↔listing 关联 (own 4989 + comp 2851) | 评论归属分析 |
| product_listings | HDV1_Channel_Listings | 357 | listing (93 竞品 + 264 自家) | 链接链路 |
| product_variants | HDV1_Product_Variants | 357 | variant (1:1 当前) | 链接链路 |
| products | HDV1_Products | 353 | product (93 竞品 + 260 自家) | 链接链路 |
| brands | HDV1_Brands | 22 | 品牌 (21 竞品 + SONKUKI) | 链接链路 |
| listing_snapshots | HDV1_Listing_Snapshots | 93 | 价格/库存快照 (解析后) | 价格历史 |
| raw_listing_snapshots | HDV1_Raw_Listing_Snapshots | 94 | 原始快照归档 (payload) | 历史审计 |
| ingestion_runs | HDV1_Ingestion_Runs | 6 | 采集运行记录 | 运维 |
| source_registry | HDV1_Source_Registry | 3 | 源注册 | 运维 |

## Key 格式

- review_key:`HOME_DEPOT:<numeric>` (竞品) / `HOME_DEPOT:OWN:<sha1>` (自家)
- listing_key:`HOME_DEPOT:<itemId>`
- variant_key:`VARIANT:SONKUKI:<itemId>` (自家) / 竞品沿用原格式
- product_key:`PRODUCT:SONKUKI:<mpn>` (自家) / `PRODUCT:BRAND:<brand>:<mpn>` (竞品)
- brand_key:`BRAND:SONKUKI` / `BRAND:<brand>`
- 跨渠道 join:sonkuki_products ↔ homedepot_products 通过 product_key (tracker `inputs/homedepot_sf_mpn_tracker.tsv` 已回填 30 个)

## 评论链路 (分析层核心)

```
reviews.review_key
  → review_listing_links (review_key, listing_key)
  → product_listings (listing_key → variant_key)
  → product_variants (variant_key → product_key)
  → products (product_key → brand_key)
  → brands
```

自家评论另有 item_id 直接连 homedepot_products (回填完成,4989/4989);product_key 连 sonkuki_products (12 个 tracker 映射可 join)。

## 已知边界

1. **competitor_sales 无法 join 到商品** — 名称格式不匹配 (78 行仅 1 行 name-match);按品牌/品类聚合使用,如需 join 需名称规范化 (低优先)。
2. **自家评论 → 官网 join 仅 12/31 商品** — tracker 覆盖的产品才有 product_key 关联;其余 HD 商品无对应官网目录记录。
3. **产品链当前 1:1:1** (products/product_variants/product_listings 行数相同) — 支持未来多 variant,当前无一对多。
4. **快照双存**:listing_snapshots (解析后) vs raw_listing_snapshots (payload 归档) — 设计如此,历史审计用。
5. **gsc_keyword_month 等派生表** 与 gsc_raw 存在同源重复 — 报表消费,不维护为源。

## 变更纪律

- 评论增删改:只动 reviews 表 (含 is_own 标记),不要新建评论表
- 采集入库:写采集层扁平表 (带 itemId/url/product_key)
- 需要评论归属时:走 review_listing_links 链路,不直接 join 扁平表
- 删除任何表前:全库导出备份 (scripts/export_all_tables_xlsx.py)
