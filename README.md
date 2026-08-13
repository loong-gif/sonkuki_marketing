# SONKUKI Marketing Insights

SONKUKI（Home Depot 卖家）的 Google Search Console（GSC）关键词洞察与市场对标分析项目。

- **GSC 关键词洞察**：抓取/整理 GSC 关键词数据，做查询相关性清洗（VALID / IRRELEVANT / UNKNOWN），只让 VALID 查询进入 Keyword Opportunity。
- **Home Depot 市场对标 Benchmark**：自有商品（Product Units）与 Home Depot 竞品对比（价格、评分、评论、低星占比、行动建议），输出到 dashboard 的「市场对标 Benchmark」页面。
- **Dashboard**：静态站点（worker + public），部署在 Vercel / Sites，快照数据由 `scripts/build_dashboard_snapshot.mjs` 构建。

## 目录结构

```
├── scripts/          # 主要脚本（Python + Node.mjs）：数据抓取、清洗、快照构建、对标计算
├── tests/            # 测试（pytest/unittest + node --test）
├── docs/             # 架构文档
├── inputs/           # 输入数据（如 MPN tracker）
├── outputs/          # 生成产物（不入库：快照、导出、站点、原始评论等）
├── *.md              # 各模块规范 / handoff 文档
├── *.py              # 顶层分析脚本（GSC 分析等）
└── *.csv             # Shopify ↔ Home Depot 商品映射
```

## 快速开始

依赖：Python 3、Node.js（>= 18）、NocoDB 凭据（`credentials.txt`，**不入库**，按 `scripts/` 中脚本的读取路径放置）。

刷新流程（在仓库根目录运行）：

```bash
# 1. 查询相关性清洗（GSC 数据变化后重跑）
python3 scripts/classify_query_relevance.py

# 2. 重建快照 + 站点
node scripts/build_dashboard_snapshot.mjs
cd outputs/sonkuki_gsc_insights_site
npm run build
npm run validate
npm test

# 3. 发布（临时宿主）
vercel deploy --prod
```

运行测试：

```bash
python3 -m unittest discover -s tests
cd outputs/sonkuki_gsc_insights_site && npm test
```

## 敏感信息

- `credentials.txt`（NocoDB 凭据）**绝不提交、不公开**。
- 原始评论文本、评价者姓名、位置等信息**不入库**（生成数据位于 `outputs/`，已被 `.gitignore` 排除）。
- 在公开仓库中操作时，请勿通过 PR / issue / 评论贴出任何凭据或原始数据。

## 发布

- **Vercel**（临时）：项目 `sonkuki-gsc-insights` 已链接在 `outputs/sonkuki_gsc_insights_site/.vercel/project.json`；`vercel.json` 通过 `node scripts/export_vercel_static.mjs` 构建并托管 `public/`。
- **Sites**（OpenAI ChatGPT 托管，待积分）：见 `outputs/sonkuki_gsc_insights_site/.openai/hosting.json`。该站点目录是独立的 git 仓库，不并入本仓库。

## 相关规范文档

- `SONKUKI_HANDOFF.md` — 项目交接与当前状态
- `homedepot_competitors_compare.md` — 市场对标模块规范
- `irrelevant_query_clean.md` — 查询相关性清洗规范
- `keyword_cannibalization.md` — 关键词蚕食分析
- `dashboard_restructure_review.md` — dashboard 结构评审
- `docs/schema_architecture.md` — NocoDB 表结构架构
