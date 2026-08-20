# Sonkuki 数据库架构说明 (HDV1 分析链)

> 更新: 2026-08-20。Base: Sonkuki (`p447va1t8jqqjty`)，**14 张活跃表**，全部 snake_case 命名。
> 2026-08 已删除采集层扁平表与管线元数据表；评论归属、市场对标、GSC 洞察均走 HDV1 规范化链。

## 总体结构

```
┌─────────────────────────────────────────────────────────────┐
│  官网目录                                                    │
│  sonkuki_products (Shopify 商品)                              │
├─────────────────────────────────────────────────────────────┤
│  HDV1 分析链 — 评论 / listing / 市场对标的唯一商品来源       │
│  brands → products → product_variants → product_listings →  │
│  review_listing_links → reviews                              │
│  listing_snapshots (价格/库存快照)                            │
├─────────────────────────────────────────────────────────────┤
│  GSC 域                                                      │
│  gsc_raw ↔ gsc_page_all_time / gsc_keyword_all_time         │
│  gsc_keyword_month / gsc_keyword_improved / gsc_keyword_newly_ranked │
└─────────────────────────────────────────────────────────────┘
```

## 已删除表 (勿再引用)

以下表已于 2026-08 从 NocoDB 移除，相关脚本已标记 DEPRECATED：

| 旧 title | 旧 table id | 原职责 |
|---|---|---|
| homedepot_products | `mnttfzrhu6gp6s0` | 自家 HD listing 扁平表 |
| competitor_products | `m0vk08vypm4jrl7` | 竞品商品扁平表 |
| competitor_sales | `munzznlmfzd9d2t` | 竞品销量估算 |
| raw_listing_snapshots | `mzi7pcyvcg0865m` | 原始快照 payload 归档 |
| ingestion_runs | — | 采集运行记录 |
| source_registry | — | 源注册 |

## 活跃表清单 (14)

| 表 (title) | table id | 行数 (2026-08-20 audit) | 职责 | 消费者 |
|---|---|---|---|---|
| reviews | `mnz1y5x5kydob4f` | 9,762 | **唯一评论源** (`is_own` 区分自家/竞品) | 评论分析、看板、市场对标 |
| review_listing_links | `m040fohool0kx56` | 13,401 | 评论 ↔ listing 关联 | 评论归属、看板 |
| product_listings | `m7xynlp62mphmlv` | 669 | 渠道 listing (HD itemId) | 链接链路、市场对标 |
| product_variants | `m1br71dforlpotk` | 698 | SKU / variant | 链接链路、Product Units |
| products | `m2w1cuciam30ltz` | 676 | 逻辑商品 | 链接链路、Product Units |
| brands | `m7ue920zwzocr6t` | 71 | 品牌 | 链接链路、市场对标分组 |
| listing_snapshots | `mq2abnm4fqtz1f5` | — | 价格/库存快照 (解析后) | 价格历史 |
| sonkuki_products | `ma3331finostkis` | 31 | sonkuki.com 官网目录 | 看板 Product SEO |
| gsc_raw | `mfbg6s0mv9l74ky` | 12,389 | GSC 明细 (含 `branded_type` 等) | 看板 GSC 各页 |
| gsc_keyword_all_time | `muav8zitnoqlauu` | 2,013 | 关键词维度 + 相关性分类 | 看板 Keyword Opportunity |
| gsc_page_all_time | `m0fl1tcxyopz1s3` | 242 | 页面维度 | 看板 GSC 页面分析 |
| gsc_keyword_month | `m0e006r2m3d1wg5` | 3,101 | 月度关键词报表 | 报表 / BI |
| gsc_keyword_improved | `m1eh0kd0ryxeptu` | 88 | 排名改善关键词 | 报表 / BI |
| gsc_keyword_newly_ranked | `mj3l8mejz31n8ry` | 116 | 新上榜关键词 | 报表 / BI |

## Key 格式

- **review_key**: `HOME_DEPOT:<numeric>` (竞品) / `HOME_DEPOT:OWN:<sha1>` (自家)
- **listing_key**: `HOME_DEPOT:<itemId>`
- **variant_key**: `VARIANT:SONKUKI:<itemId>` (自家) / 竞品沿用迁移时生成的格式
- **product_key**: `PRODUCT:SONKUKI:<mpn>` (自家) / `PRODUCT:BRAND:<brand>:<mpn>` (竞品)
- **brand_key**: `BRAND:SONKUKI` / `BRAND:<brand>`

跨渠道 join：`sonkuki_products.product_key` ↔ `products.product_key`（tracker `inputs/homedepot_sf_mpn_tracker.tsv` 已映射 30 个 MPN）。

## 分析链 (核心)

```
reviews.review_key
  → review_listing_links (review_key, listing_key)
  → product_listings (listing_key → variant_key)
  → product_variants (variant_key → product_key)
  → products (product_key → brand_key)
  → brands
```

- 自家评论：`is_own=1`，经 `review_listing_links` 归属到 `HOME_DEPOT:<itemId>` listing。
- 竞品评论：`is_own≠1`，同样走 links → listings 链路；市场对标从 listings / variants / products 聚合 Product Units。
- 官网商品：`sonkuki_products` 独立维护 Shopify 目录；通过 `product_key` 与 HDV1 `products` 对齐（非 1:1 全覆盖）。

## 消费者脚本

| 脚本 | 读取的表 |
|---|---|
| `scripts/build_dashboard_snapshot.mjs` | gsc_*、sonkuki_products、reviews、review_listing_links、product_listings、product_variants |
| `scripts/competitor_benchmark.mjs` | 由 snapshot 中的 listings / reviews / variants 驱动 (离线 runner: `run_competitor_benchmark.mjs`) |
| `scripts/classify_query_relevance.py` | gsc_keyword_all_time |
| `scripts/orphan_audit.py` | HDV1 链 + sonkuki_products + gsc_* (只读审计) |

> `build_top10_snapshot.mjs` 在计划中作为 Top-10 低 CTR 快照拆分目标；当前 Top-10 指标仍由 `build_dashboard_snapshot.mjs` 内嵌计算。

## 已知边界

1. **sonkuki_products ↔ products 非全覆盖** — tracker 映射约 30/31 官网 SKU；其余 HD listing 无对应官网行。
2. **product_variants 行数 ≥ product_listings** — 支持一对多 variant；当前多数为 1:1，markets 对标按 Product Unit 聚合。
3. **gsc_keyword_month 等派生表** 与 gsc_raw 同源 — 报表消费，不以派生表为写入源。
4. **listing_snapshots** 仅存解析后字段 — 原始 payload 表已删除。

## 变更纪律

- 评论增删改：只动 `reviews`（含 `is_own`），不新建评论表。
- 商品 / listing 变更：走 HDV1 链 (brands → … → listings)，不再写已删扁平表。
- 评论归属：必须经 `review_listing_links`，不直接按 `item_id` 跳表 join。
- 删除任何表前：全库导出备份 (`scripts/export_all_tables_xlsx.py`)。
