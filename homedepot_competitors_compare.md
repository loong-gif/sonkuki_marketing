# Home Depot 自家与竞品市场分析执行方案

现有数据已经包含 SONKUKI 的 Home Depot 商品价格、评分、评论数和型号信息，并有 Shopify 与 Home Depot 商品匹配数据；同时具备 Home Depot Pergola 竞品 Top Sellers 数据，可以直接以 Pergola 作为第一批试点。

> 状态：Pergola 试点已跑通（2026-08-13）。实现位于 `scripts/competitor_benchmark.mjs`（纯函数模块）+ `scripts/run_competitor_benchmark.mjs`（运行器），Dashboard 新增「市场对标 Benchmark」页。运行：`node scripts/run_competitor_benchmark.mjs`（默认 Pergola，可传其他品类）。输出写入 `outputs/competitor_benchmark_*_2026-08-13.{csv,json}`。

## 第一步：整理数据

* [x] 区分 SONKUKI 商品和竞品商品 — 统一表带 `side` 字段（own / competitor）
* [x] 统一品牌、品类、尺寸、价格、评分、评论数
* [x] 去除重复 Listing — 按 Home Depot Item ID 去重（26 → 23 个 Pergola SKU）
* [x] 标记数据快照日期 — `snapshot_date` 列

**输出：** `outputs/competitor_benchmark_unified_2026-08-13.csv`（统一 Home Depot 商品表）。

---

## 第二步：建立可比商品组（产品单位）

先以 Pergola 为试点，自家与竞品都区分 **Product Unit 与 Listing**，核心对比统一按 Product Unit 计算：

* 自家产品单位 = 同一规格组（Category × Size × Material + 核心功能）的变体 SKU 合并（23 SKU → 8 单位）
* 竞品产品单位 = 品牌 × 规格组（299 listings → 191 单位），单位价格取 listing 中位数、评分按评论量加权、评论取合计
* Listing 数仅表示市场覆盖情况

匹配层级（第一层非空即用）：`exact` 精确（核心功能 + 材质 + 尺寸）→ `tolerance` 尺寸容差 ±1ft → `size` 同尺寸（材质放宽）→ `material` 同材质（尺寸放宽）→ `none` 无竞品组。宽口径组标记 `wide=yes`，匹配质量映射为 `高/中/低置信度 / 无可比`。

例如：

`Louvered Pergola · 12×14 ft · Steel`

**输出：** `outputs/competitor_benchmark_groups_2026-08-13.csv`（每 SKU 竞品组）+ `outputs/competitor_benchmark_units_2026-08-13.csv`（产品单位聚合表）+ `outputs/competitor_benchmark_coverage_2026-08-13.json`（覆盖统计）。

---

## 第三步：完成核心对比

每个 SONKUKI 产品单位比较：

* 自家价格 vs 竞品单位中位价（价格差显示为 `高于竞品 16%` / `低于竞品 8%`）
* 自家评分 vs 竞品评分（中位，保留两位小数；无评论显示 `—`）
* 自家评论数 vs 竞品评论中位数
* 自家低星评论占比 vs 竞品（自家评论 ≥5 条才计算，防小样本误判）
* 主要负面评论主题

**输出：** `outputs/competitor_benchmark_skus_2026-08-13.csv`（SKU 明细）+ `outputs/competitor_benchmark_units_2026-08-13.csv`（单位对比表）。

---

## 第四步：生成行动建议

每个产品单位只给一条主要建议（确定性规则，`scripts/competitor_benchmark.mjs` 的 `recommend()` + `actionDetail()`），每条行动含：产品组 / 问题 / 关键证据 / 建议：

* 保持价格
* 检查价格溢价 — 价格差 ≥ +10% 才触发
* 建立社会证明 — 无评论商品优先触发
* 增加评论积累 — 评分差距 < 0.1（视为持平）且评论 < 中位 × 0.5
* 改善安装体验 — 低星占比高且主导主题为 Assembly & parts
* 改善材料或耐用性 — 低星占比高且主导主题为 Durability & material
* 强化产品卖点 — 评分落后中位 0.1+ 或低星主题为 Other（不作为产品行动）
* 补充产品覆盖 — 该规格在竞品中无同口径基准

匹配质量为 `低置信度` 时，建议附 `（匹配质量较低，建议人工核验）` 提示。

**输出：** `outputs/competitor_benchmark_actions_2026-08-13.json`（优先处理的 5–10 个产品单位，当前 5 个）。

---

## Dashboard 第一版（优化版）

已实现，新增「市场对标 Benchmark」导航页：

### Benchmark Coverage（原 Market Overview）

* 自家 8 产品单位 / 23 Listings；竞品 191 产品单位 / 299 Listings
* 匹配质量：5 精确 / 3 近似 / 0 无可比
* 中位价格、加权评分、评论总量
* `Scope：Pergola` + `Home Depot Snapshot Date`

### Product Benchmark

* 产品单位表：第一列真实产品组名（如 `Louvered Pergola · 12×14 ft · Steel`），SKU 数与竞品数在副标题
* 价格区间与中位价、竞品单位中位价、价格差（百分比）、评分（两位小数，无评论 `—`）、评论量
* 匹配层级 badge + 展开 SKU 明细

### VOC Comparison

* 显示自家与竞品低星评论样本量
* 自家低星 < 10 条时显示 `样本不足，暂不判断市场差异`，不输出高于/差于市场结论
* 差值统一用百分点（如 `+8.2 pp`）
* `Other` 不作为主要产品行动建议

### 筛选器

Category / Size / Material / Competitor Brand / Match Quality（当前仅 Pergola 品类有数据）。

---

## 执行周期

### Day 1

数据与规则：统一 Product Unit / Listing 口径、修复评分与价格差显示、VOC 样本门槛、行动触发规则 — 已完成。

### Day 2

页面更新：Benchmark Coverage、Product Benchmark 表、Priority Actions、VOC 区域、筛选器 — 已完成。

### Day 3

QA 与发布：数字格式、无评论显示、口径一致性、行动建议核对、发布 Pergola MVP — 已完成。

---

## 验收标准

* [x] 自家和竞品使用一致的比较单位 — 双方均按产品单位计算对比基准
* [x] 每一行可以直接看出具体产品组 — 第一列真实组名 + 副标题
* [x] 无评分商品不再显示为 0 分 — 显示 `—`
* [x] 小样本 VOC 不再生成强结论 — <10 条显示样本不足
* [x] 所有百分比和评分格式统一 — 价格差百分比、评分两位小数、VOC 用 pp
* [x] 每个重点产品组只有一条清晰的主要行动 — 产品组/问题/证据/建议
* [x] 用户可以理解匹配质量和结论可信度 — 高/中/低置信度 + 低置信度提示
* [x] Pergola 模块跑通后，可复制到 Umbrella 和 Patio Furniture — 模块按 category 参数驱动
