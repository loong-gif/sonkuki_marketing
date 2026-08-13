"""Reproducible, dependency-free analysis for a Sonkuki GSC export.

The module keeps raw source rows separate from bounded report datasets.  It is
safe to import in tests and does not perform network or database operations.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit, urlunsplit


MEANINGFUL_COLUMNS = (
    "id",
    "site_url",
    "date",
    "page",
    "query",
    "clicks",
    "impressions",
    "ctr",
    "position",
)

BRAND_RE = re.compile(r"(?:sonkuki|son[\s-]?uki|sankuki|sonku\b|zimi\s+america)", re.I)
REVIEW_TERMS = ("review", "reviews", "rating", "ratings", "feedback")
SPEC_TERMS = ("size", "ft", "feet", "led", "solar", "louver", "louvered", "drainage", "material", "base")
INFO_TERMS = ("best", "how", "guide", "comparison", "compare", "for ", "ways to", "ideas", "durability", "store", "worth")
UMBRELLA_TERMS = ("umbrella", "parasol", "shade")
PERGOLA_TERMS = ("pergola", "louver")
FURNITURE_TERMS = ("furniture", "chair", "sofa", "sectional", "table", "ottoman", "dining", "bistro")
ACCESSORY_TERMS = ("base", "cover", "screen", "accessor")


def normalize_query(value: str) -> str:
    """Normalize query text without discarding the original query."""
    normalized = unicodedata.normalize("NFKC", value or "").lower().strip()
    return re.sub(r"\s+", " ", normalized)


def normalize_page(value: str) -> str:
    """Canonicalize a page URL for aggregation while preserving path identity."""
    raw = (value or "").strip()
    if not raw:
        return raw
    parsed = urlsplit(raw)
    scheme = "https" if parsed.scheme.lower() in ("http", "https") else parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, "", ""))


def parse_percent(value: str) -> float:
    text = str(value or "").strip().replace(",", "")
    if text.endswith("%"):
        return float(text[:-1]) / 100
    return float(text or 0)


def load_rows(path: str | Path) -> list[dict]:
    """Read only the nine meaningful columns from the wide GSC export."""
    rows: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if len(header) < 9 or header[1] != "site_url（属性）":
            raise ValueError("unexpected GSC export header")
        for values in reader:
            if len(values) < 9:
                raise ValueError("row has fewer than nine source columns")
            rows.append(
                {
                    "site_url": values[1].strip(),
                    "date": date.fromisoformat(values[2].strip()).isoformat(),
                    "page": values[3].strip(),
                    "query": values[4].strip(),
                    "clicks": int(values[5]),
                    "impressions": int(values[6]),
                    "ctr_source": parse_percent(values[7]),
                    "position_source": float(values[8]),
                }
            )
    return rows


def classify_brand(query: str) -> str:
    return "品牌" if BRAND_RE.search(normalize_query(query)) else "非品牌"


def is_suspicious_query(query: str) -> bool:
    """Flag obvious non-target/spam-like queries without deleting source rows."""
    q = normalize_query(query)
    if "customer service phone number" in q:
        return True
    domains = re.findall(r"\b[a-z0-9-]+\.(?:com|net|org)\b", q)
    return any(domain not in ("sonkuki.com",) for domain in domains)


def classify_intent(query: str, brand_class: str | None = None) -> str:
    q = normalize_query(query)
    if any(term in q for term in REVIEW_TERMS):
        return "评价/信任"
    if any(term in q for term in INFO_TERMS):
        return "信息/使用场景"
    if any(term in q for term in SPEC_TERMS) or re.search(r"\b\d+(?:\.\d+)?\s*(?:x|ft|feet)\b", q):
        return "规格/尺寸"
    if any(term in q for term in ("patio", "outdoor", "garden", "backyard", "pool", "pergola", "umbrella", "furniture", "chair", "sofa")):
        return "品类购物"
    if brand_class == "品牌" or classify_brand(q) == "品牌":
        return "导航"
    return "其他"


def classify_theme(query: str, page: str = "") -> str:
    text = f"{normalize_query(query)} {normalize_query(page)}"
    if any(term in text for term in ACCESSORY_TERMS):
        return "Accessories"
    if any(term in text for term in PERGOLA_TERMS):
        return "Pergola"
    if any(term in text for term in UMBRELLA_TERMS):
        return "Umbrella"
    if any(term in text for term in FURNITURE_TERMS):
        return "Furniture"
    if any(term in text for term in ACCESSORY_TERMS):
        return "Accessories"
    return "其他"


def enrich_rows(rows: list[dict]) -> list[dict]:
    enriched = []
    for row in rows:
        copy = dict(row)
        copy["canonical_page"] = normalize_page(row["page"])
        copy["normalized_query"] = normalize_query(row["query"])
        copy["brand_class"] = classify_brand(row["query"])
        copy["intent"] = classify_intent(row["query"], copy["brand_class"])
        copy["theme"] = classify_theme(row["query"], row["page"])
        copy["suspicious_query"] = is_suspicious_query(row["query"])
        enriched.append(copy)
    return enriched


def _aggregate(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        bucket = buckets.setdefault(
            key,
            {**{k: value for k, value in zip(keys, key)}, "clicks": 0, "impressions": 0, "weighted_position_sum": 0.0, "rows": 0, "raw_pages": set(), "raw_queries": set(), "dates": set()},
        )
        bucket["clicks"] += row["clicks"]
        bucket["impressions"] += row["impressions"]
        bucket["weighted_position_sum"] += row["position_source"] * row["impressions"]
        bucket["rows"] += 1
        bucket["raw_pages"].add(row["page"])
        bucket["raw_queries"].add(row["normalized_query"])
        bucket["dates"].add(row["date"])
    output = []
    for bucket in buckets.values():
        impressions = bucket["impressions"]
        output.append(
            {
                **{key: bucket[key] for key in keys},
                "clicks": bucket["clicks"],
                "impressions": impressions,
                "ctr": bucket["clicks"] / impressions if impressions else 0.0,
                "weighted_position": bucket["weighted_position_sum"] / impressions if impressions else 0.0,
                "rows": bucket["rows"],
                "raw_page_count": len(bucket["raw_pages"]),
                "query_count": len(bucket["raw_queries"]),
                "observed_days": len(bucket["dates"]),
            }
        )
    return output


def _sort_rows(rows: list[dict], field: str = "clicks") -> list[dict]:
    return sorted(rows, key=lambda row: (-row.get(field, 0), -row.get("impressions", 0), str(row.get("canonical_page", row.get("normalized_query", "")))))


def _date_profile(rows: list[dict]) -> dict:
    dates = sorted({date.fromisoformat(row["date"]) for row in rows})
    missing: list[str] = []
    if dates:
        cursor = dates[0]
        end = dates[-1]
        while cursor <= end:
            if cursor not in dates:
                missing.append(cursor.isoformat())
            cursor += timedelta(days=1)
    return {"date_min": dates[0].isoformat(), "date_max": dates[-1].isoformat(), "distinct_dates": len(dates), "missing_dates": missing}


def _weekly(rows: list[dict]) -> list[dict]:
    by_day = _aggregate(rows, ("date",))
    day_map = {date.fromisoformat(row["date"]): row for row in by_day}
    if not day_map:
        return []
    first = min(day_map)
    last = max(day_map)
    cursor = first - timedelta(days=first.weekday())
    output = []
    while cursor <= last:
        days = [cursor + timedelta(days=i) for i in range(7)]
        observed = [day_map[d] for d in days if d in day_map]
        if observed:
            clicks = sum(item["clicks"] for item in observed)
            impressions = sum(item["impressions"] for item in observed)
            output.append({"week": cursor.isoformat(), "clicks": clicks, "impressions": impressions, "ctr": clicks / impressions if impressions else 0.0, "observed_days": len(observed), "complete": len(observed) == 7})
        cursor += timedelta(days=7)
    return output


def _with_brand_weekly(rows: list[dict], complete_weeks: list[dict]) -> list[dict]:
    allowed = {row["week"] for row in complete_weeks}
    grouped = _aggregate(rows, ("brand_class",))
    day_keys = defaultdict(list)
    for row in rows:
        d = date.fromisoformat(row["date"])
        week = (d - timedelta(days=d.weekday())).isoformat()
        day_keys[(week, row["brand_class"])].append(row)
    output = []
    for (week, brand), bucket_rows in sorted(day_keys.items()):
        if week not in allowed:
            continue
        clicks = sum(row["clicks"] for row in bucket_rows)
        impressions = sum(row["impressions"] for row in bucket_rows)
        output.append({"week": week, "brand_class": brand, "clicks": clicks, "impressions": impressions, "ctr": clicks / impressions if impressions else 0.0})
    return output


def _opportunities(rows: list[dict]) -> list[dict]:
    grouped = _aggregate(rows, ("normalized_query", "canonical_page", "brand_class", "intent", "theme"))
    by_bucket: dict[str, list[float]] = defaultdict(list)
    for item in grouped:
        position = item["weighted_position"]
        bucket = "1-3" if position <= 3 else "4-10" if position <= 10 else "11-20" if position <= 20 else "21+"
        by_bucket[bucket].append(item["ctr"])
    medians = {bucket: median(values) if values else 0.0 for bucket, values in by_bucket.items()}
    candidates = []
    for item in grouped:
        if item["impressions"] < 30:
            continue
        position = item["weighted_position"]
        bucket = "1-3" if position <= 3 else "4-10" if position <= 10 else "11-20" if position <= 20 else "21+"
        bucket_median = medians.get(bucket, 0.0)
        reasons = []
        if bucket_median and item["ctr"] < bucket_median * 0.75:
            reasons.append("高曝光低CTR")
        if 4 <= position <= 20:
            reasons.append("排名提升空间")
        if item["intent"] in ("评价/信任", "规格/尺寸"):
            reasons.append("高意图承接")
        if item["raw_page_count"] > 1:
            reasons.append("URL参数分散")
        if not reasons:
            continue
        gap = max(0.0, 1.0 - (item["ctr"] / bucket_median if bucket_median else 0.0))
        priority = item["impressions"] * (1 + gap) * (1.25 if item["intent"] in ("评价/信任", "规格/尺寸") else 1.0)
        if "高曝光低CTR" in reasons:
            action = "重写标题/描述与结构化摘要，核对搜索意图与首屏承诺"
        elif "排名提升空间" in reasons:
            action = "补充对应主题内容、内链和页面证据，争取进入前十"
        else:
            action = "建立专题或 FAQ 承接页，并统一规范 URL"
        candidates.append({**item, "issue": "；".join(reasons), "action": action, "priority_score": round(priority, 2)})
    candidates.sort(key=lambda item: (-item["priority_score"], -item["impressions"], item["normalized_query"], item["canonical_page"]))
    for index, item in enumerate(candidates, start=1):
        item["rank"] = index
    return candidates[:25]


def _round_numeric(rows: list[dict]) -> list[dict]:
    cleaned = []
    for row in rows:
        copy = dict(row)
        for key in ("ctr", "weighted_position", "priority_score"):
            if key in copy and isinstance(copy[key], float):
                copy[key] = round(copy[key], 6)
        cleaned.append(copy)
    return cleaned


def analyze(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("no GSC rows")
    enriched = enrich_rows(rows)
    total_clicks = sum(row["clicks"] for row in enriched)
    total_impressions = sum(row["impressions"] for row in enriched)
    weighted_position_sum = sum(row["position_source"] * row["impressions"] for row in enriched)
    raw_keys = Counter((row["site_url"], row["date"], row["page"], row["query"]) for row in enriched)
    source_ctr_mismatches = sum(abs(row["ctr_source"] - (row["clicks"] / row["impressions"] if row["impressions"] else 0)) > 0.000051 for row in enriched)
    profile = _date_profile(enriched)
    weekly = _weekly(enriched)
    complete_weeks = [row for row in weekly if row["complete"]]
    brand_mix = _sort_rows(_aggregate(enriched, ("brand_class",)))
    market_rows = [row for row in enriched if not row["suspicious_query"]]
    intent_mix = _sort_rows(_aggregate(market_rows, ("intent",)))
    theme_mix = _sort_rows(_aggregate(market_rows, ("theme",)))
    landing_pages = _sort_rows(_aggregate(enriched, ("canonical_page",)), "clicks")
    for index, row in enumerate(landing_pages, start=1):
        row["rank"] = index
        row["page_label"] = row["canonical_page"].replace("https://sonkuki.com", "") or "/"
    opportunities = _opportunities(market_rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": "sonkuki_gsc_export_SCD_Raw.csv",
        "rows": enriched,
        "profile": profile,
        "metrics": {
            "row_count": len(enriched),
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "overall_ctr": total_clicks / total_impressions if total_impressions else 0.0,
            "weighted_position": weighted_position_sum / total_impressions if total_impressions else 0.0,
            "raw_page_count": len({row["page"] for row in enriched}),
            "canonical_page_count": len({row["canonical_page"] for row in enriched}),
            "raw_query_count": len({row["query"] for row in enriched}),
            "query_count": len({row["normalized_query"] for row in enriched}),
            "site_count": len({row["site_url"] for row in enriched}),
            "duplicate_grain_rows": sum(count - 1 for count in raw_keys.values() if count > 1),
            "duplicate_grain_keys": sum(1 for count in raw_keys.values() if count > 1),
            "ctr_source_mismatches": source_ctr_mismatches,
            "clicks_gt_impressions": sum(row["clicks"] > row["impressions"] for row in enriched),
            "suspicious_query_rows": sum(row["suspicious_query"] for row in enriched),
            "suspicious_query_impressions": sum(row["impressions"] for row in enriched if row["suspicious_query"]),
            "suspicious_query_clicks": sum(row["clicks"] for row in enriched if row["suspicious_query"]),
        },
        "weekly": weekly,
        "weekly_complete": complete_weeks,
        "weekly_brand": _with_brand_weekly(enriched, complete_weeks),
        "brand_mix": brand_mix,
        "intent_mix": intent_mix,
        "theme_mix": theme_mix,
        "landing_pages": landing_pages[:25],
        "opportunities": opportunities,
    }


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _compact(value: float) -> str:
    if value >= 1000000:
        return f"{value / 1000000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:,.0f}"


def build_artifact(analysis: dict) -> dict:
    metrics = analysis["metrics"]
    brand_clicks = next((row["clicks"] for row in analysis["brand_mix"] if row["brand_class"] == "品牌"), 0)
    brand_share = brand_clicks / metrics["total_clicks"] if metrics["total_clicks"] else 0
    top_brand = max(analysis["brand_mix"], key=lambda row: row["clicks"])
    top_intent = max(analysis["intent_mix"], key=lambda row: row["clicks"])
    top_theme = max(analysis["theme_mix"], key=lambda row: row["clicks"])
    top_page = analysis["landing_pages"][0]
    profile = analysis["profile"]
    missing = "、".join(profile["missing_dates"]) if profile["missing_dates"] else "无"
    gsc_source = {
        "id": "gsc_csv",
        "label": "GSC 导出：SCD_Raw.csv",
        "path": "sonkuki_gsc_export_SCD_Raw.csv",
        "query": {
            "language": "python",
            "description": "读取 CSV 的九个有效字段；按日期、页面、查询词聚合，CTR 为点击除以曝光，排名按曝光加权。",
            "sql": "SELECT site_url, date, page, query, clicks, impressions, ctr, position FROM gsc_csv WHERE site_url = 'sc-domain:sonkuki.com' AND date BETWEEN '2026-04-22' AND '2026-08-08'",
            "filters": [f"date between {profile['date_min']} and {profile['date_max']}", "site property = sc-domain:sonkuki.com"],
            "metric_definitions": {
                "ctr": "sum(clicks) / sum(impressions)",
                "weighted_position": "sum(position * impressions) / sum(impressions)",
                "brand_class": "query matches Sonkuki brand variants or ZIMI America",
            },
        },
    }
    website_source = {
        "id": "website_context",
        "label": "SONKUKI 官网类目与承诺",
        "href": "https://sonkuki.com/",
        "query": {"description": "只用于核对类目、产品承诺与落地页承接，不作为 GSC 指标来源。"},
    }
    source_id = "gsc_csv"
    summary = (
        f"- **点击高度集中在品牌需求。** 品牌词贡献 {_pct(brand_share)} 的点击；这说明已有品牌认知，但不能单独证明非品牌获客能力。\n"
        f"- **搜索需求以 {top_theme['theme']} 和 {top_intent['intent']} 为主要入口。** 报告将把曝光、点击、CTR 与排名放在同一口径下解释。\n"
        f"- **最重要的承接页面是 `{top_page['page_label']}`。** 它获得 {_compact(top_page['clicks'])} 点击、{_compact(top_page['impressions'])} 曝光，后续机会按页面和查询簇排序。\n"
        "- **结论是搜索需求代理信号。** GSC 不包含订单、收入、设备、国家或用户级转化；数据库增强仅在安全且可关联时加入。"
    )
    scope = (
        f"数据覆盖 {profile['date_min']} 至 {profile['date_max']}，共 {metrics['row_count']:,} 行、{metrics['site_count']} 个属性、"
        f"{metrics['raw_page_count']} 个原始 URL、{metrics['canonical_page_count']} 个规范页面、{metrics['raw_query_count']} 个原始查询和 {metrics['query_count']} 个规范查询。\n\n"
        f"总量指标保留 {metrics['suspicious_query_rows']} 行明显非目标查询（{metrics['suspicious_query_clicks']} 点击、{metrics['suspicious_query_impressions']} 曝光）；意图、主题和机会表排除这些查询以避免市场信号污染。\n\n"
        f"缺失日期：{missing}。4 月和 8 月均为不完整月份，因此趋势只使用日均、完整周和等长窗口。"
    )
    trend_note = "完整周趋势用于观察变化形状；缺失日不补零。品牌/非品牌序列用于区分已有认知与新增获客信号。"
    brand_note = f"品牌点击占 {_pct(brand_share)}；请将其视为品牌需求与导航需求，不要当作非品牌 SEO 增长。"
    intent_note = f"点击最多的意图是 {top_intent['intent']}；规格、尺寸和评价词会在机会表中单独标记，因为它们更接近购买决策。"
    theme_note = f"产品主题按查询词与落地页联合分类；当前点击最多的主题为 {top_theme['theme']}。"
    page_note = f"入口页按规范 URL 聚合，页面 `{top_page['page_label']}` 排名第一；带参数 URL 的分散情况单独进入机会识别。"
    opportunity_note = "机会表使用至少 30 次曝光的查询-页面组合，并按曝光、排名空间、CTR 缺口和高意图信号排序；这是优先级工具，不是因果模型。"
    recommendations = (
        "1. **先保护品牌入口，再扩大非品牌入口。** 将品牌词与非品牌词分开看 KPI，避免品牌点击增长掩盖品类搜索能力。\n"
        "2. **优先修复高曝光低 CTR 页面。** 对标题、描述、首屏承诺、价格/尺寸/材质信息和结构化摘要做页面级迭代。\n"
        "3. **把规格、尺寸、评价需求转成可索引内容。** 建立尺寸选择、安装/排水、LED/材质、底座和评价 FAQ 的承接模块。\n"
        "4. **统一规范 URL 与内链。** 减少参数页分散，保证同一产品主题集中到可排名的 canonical 页面。\n"
        "5. **补接 GA4/订单数据。** 在安全连接成立后，以日期与页面/商品汇总验证哪些自然搜索入口真正产生商业结果。"
    )
    caveats = (
        "- GSC 能说明曝光、点击、CTR、排名和搜索意图代理信号，不能直接说明市场规模、用户满意度或购买因果。\n"
        "- 数据存在缺失日期和不完整月份；报告不将缺失日解释为零流量。\n"
        "- 品牌规则、意图规则和主题规则是可复核的启发式分类，保留“其他”桶，后续可按业务词表迭代。\n"
        "- 明显客服号码/外部域名查询仅保留在 GSC 总量核对中，不纳入市场意图、主题或机会排序。\n"
        "- 当前数据库凭证指向明文 HTTP 配置，本报告不会使用该 PAT。"
    )
    manifest = {
        "version": 1,
        "surface": "report",
        "title": "SONKUKI 自然搜索流量与市场机会",
        "description": "面向管理层的 GSC 流量入口、搜索意图、页面承接与优先行动报告。",
        "generatedAt": analysis["generated_at"],
        "sources": [gsc_source, website_source],
        "cards": [
            {"id": "total_clicks", "dataset": "kpi_summary", "sourceId": source_id, "metrics": [{"label": "自然点击", "field": "total_clicks", "format": "number"}, {"label": "数据截至", "field": "date_max", "format": "text"}]},
            {"id": "total_impressions", "dataset": "kpi_summary", "sourceId": source_id, "metrics": [{"label": "自然曝光", "field": "total_impressions", "format": "number"}]},
            {"id": "overall_ctr", "dataset": "kpi_summary", "sourceId": source_id, "metrics": [{"label": "加权 CTR", "field": "overall_ctr", "format": "percent"}]},
            {"id": "weighted_position", "dataset": "kpi_summary", "sourceId": source_id, "metrics": [{"label": "曝光加权排名", "field": "weighted_position", "format": "number"}]},
        ],
        "charts": [
            {"id": "weekly_trend", "title": "完整周自然点击趋势", "type": "line", "dataset": "weekly_brand", "sourceId": source_id, "encodings": {"x": {"field": "week", "type": "temporal"}, "y": {"field": "clicks", "type": "quantitative", "format": "number"}, "color": {"field": "brand_class", "type": "nominal"}, "tooltip": [{"field": "impressions", "label": "曝光", "format": "number"}, {"field": "ctr", "label": "CTR", "format": "percent"}]}},
            {"id": "brand_clicks", "title": "品牌与非品牌点击分布", "type": "bar", "dataset": "brand_mix", "sourceId": source_id, "encodings": {"x": {"field": "brand_class", "type": "nominal"}, "y": {"field": "clicks", "type": "quantitative", "format": "number"}, "tooltip": [{"field": "impressions", "label": "曝光", "format": "number"}, {"field": "ctr", "label": "CTR", "format": "percent"}]}},
            {"id": "intent_clicks", "title": "搜索意图点击分布", "type": "bar", "dataset": "intent_mix", "sourceId": source_id, "encodings": {"x": {"field": "intent", "type": "nominal"}, "y": {"field": "clicks", "type": "quantitative", "format": "number"}, "tooltip": [{"field": "impressions", "label": "曝光", "format": "number"}, {"field": "ctr", "label": "CTR", "format": "percent"}]}},
            {"id": "theme_impressions", "title": "产品主题曝光分布", "type": "bar", "dataset": "theme_mix", "sourceId": source_id, "encodings": {"x": {"field": "theme", "type": "nominal"}, "y": {"field": "impressions", "type": "quantitative", "format": "number"}, "tooltip": [{"field": "clicks", "label": "点击", "format": "number"}, {"field": "ctr", "label": "CTR", "format": "percent"}]}},
            {"id": "landing_page_clicks", "title": "主要入口页面点击", "type": "bar", "dataset": "landing_pages", "sourceId": source_id, "encodings": {"x": {"field": "page_label", "type": "nominal"}, "y": {"field": "clicks", "type": "quantitative", "format": "number"}, "tooltip": [{"field": "canonical_page", "label": "规范页面", "format": "text"}, {"field": "ctr", "label": "CTR", "format": "percent"}, {"field": "weighted_position", "label": "排名", "format": "number"}]}}
        ],
        "tables": [
            {"id": "landing_page_table", "title": "入口页面明细", "dataset": "landing_pages", "sourceId": source_id, "defaultSort": {"field": "clicks", "direction": "desc"}, "columns": [{"field": "canonical_page", "label": "规范页面"}, {"field": "clicks", "label": "点击", "format": "number"}, {"field": "impressions", "label": "曝光", "format": "number"}, {"field": "ctr", "label": "CTR", "format": "percent"}, {"field": "weighted_position", "label": "加权排名", "format": "number"}, {"field": "query_count", "label": "查询数", "format": "number"}]},
            {"id": "opportunity_table", "title": "优先机会清单", "dataset": "opportunities", "sourceId": source_id, "defaultSort": {"field": "priority_score", "direction": "desc"}, "columns": [{"field": "rank", "label": "优先级", "format": "number"}, {"field": "normalized_query", "label": "查询簇"}, {"field": "canonical_page", "label": "规范页面"}, {"field": "issue", "label": "机会类型"}, {"field": "impressions", "label": "曝光", "format": "number"}, {"field": "clicks", "label": "点击", "format": "number"}, {"field": "ctr", "label": "CTR", "format": "percent"}, {"field": "weighted_position", "label": "排名", "format": "number"}, {"field": "priority_score", "label": "优先级分数", "format": "number"}, {"field": "action", "label": "建议动作"}]},
            {"id": "data_quality_table", "title": "数据质量检查", "dataset": "data_quality", "sourceId": source_id, "defaultSort": {"field": "check_order", "direction": "asc"}, "columns": [{"field": "check_order", "label": "序号", "format": "number"}, {"field": "check", "label": "检查"}, {"field": "result", "label": "结果"}, {"field": "evidence", "label": "证据"}, {"field": "risk", "label": "影响"}]},
        ],
        "blocks": [
            {"id": "title", "type": "markdown", "body": "# SONKUKI 自然搜索流量与市场机会"},
            {"id": "executive_summary", "type": "markdown", "body": "## Executive Summary\n\n" + summary, "sourceId": source_id},
            {"id": "metrics", "type": "metric-strip", "cardIds": ["total_clicks", "total_impressions", "overall_ctr", "weighted_position"]},
            {"id": "scope", "type": "markdown", "body": "## 数据边界与可信度\n\n" + scope, "sourceId": source_id},
            {"id": "trend_note", "type": "markdown", "body": "## 流量趋势：以完整周观察变化\n\n" + trend_note, "sourceId": source_id},
            {"id": "trend_chart", "type": "chart", "chartId": "weekly_trend"},
            {"id": "brand_note", "type": "markdown", "body": "## 品牌需求与非品牌获客必须分开\n\n" + brand_note, "sourceId": source_id},
            {"id": "brand_chart", "type": "chart", "chartId": "brand_clicks"},
            {"id": "intent_note", "type": "markdown", "body": "## 搜索意图显示用户处于不同决策阶段\n\n" + intent_note, "sourceId": source_id},
            {"id": "intent_chart", "type": "chart", "chartId": "intent_clicks"},
            {"id": "theme_note", "type": "markdown", "body": "## 产品主题是市场反馈的可执行切口\n\n" + theme_note, "sourceId": source_id},
            {"id": "theme_chart", "type": "chart", "chartId": "theme_impressions"},
            {"id": "page_note", "type": "markdown", "body": "## 入口页面决定搜索需求能否被承接\n\n" + page_note, "sourceId": source_id},
            {"id": "page_chart", "type": "chart", "chartId": "landing_page_clicks"},
            {"id": "page_table", "type": "table", "tableId": "landing_page_table"},
            {"id": "opportunity_note", "type": "markdown", "body": "## 优先机会：从曝光和意图出发排序\n\n" + opportunity_note, "sourceId": source_id},
            {"id": "opportunity_table", "type": "table", "tableId": "opportunity_table"},
            {"id": "recommendations", "type": "markdown", "body": "## 建议行动\n\n" + recommendations},
            {"id": "caveats", "type": "markdown", "body": "## 进一步问题与局限\n\n" + caveats},
        ],
    }
    quality_rows = [
        {"check_order": 1, "check": "原始粒度重复", "result": "通过" if metrics["duplicate_grain_rows"] == 0 else "需处理", "evidence": f"重复键 {metrics['duplicate_grain_keys']} 个，重复行 {metrics['duplicate_grain_rows']} 行", "risk": "重复会放大点击和曝光"},
        {"check_order": 2, "check": "CTR 重算", "result": "通过" if metrics["ctr_source_mismatches"] == 0 else "需复核", "evidence": f"与源 CTR 不一致行 {metrics['ctr_source_mismatches']} 行", "risk": "避免平均行级 CTR"},
        {"check_order": 3, "check": "点击不超过曝光", "result": "通过" if metrics["clicks_gt_impressions"] == 0 else "需处理", "evidence": f"异常行 {metrics['clicks_gt_impressions']} 行", "risk": "指标有效性"},
        {"check_order": 4, "check": "日期完整性", "result": "有缺口", "evidence": f"{profile['distinct_dates']} 个有数据日期，缺失 {len(profile['missing_dates'])} 天", "risk": "月度总量不可直接比较"},
        {"check_order": 5, "check": "非目标查询隔离", "result": "已隔离", "evidence": f"{metrics['suspicious_query_rows']} 行，{metrics['suspicious_query_clicks']} 点击，{metrics['suspicious_query_impressions']} 曝光", "risk": "不隔离会污染市场意图与机会判断"},
    ]
    datasets = {
        "kpi_summary": [{"total_clicks": metrics["total_clicks"], "total_impressions": metrics["total_impressions"], "overall_ctr": round(metrics["overall_ctr"], 6), "weighted_position": round(metrics["weighted_position"], 3), "date_max": profile["date_max"]}],
        "weekly_brand": _round_numeric(analysis["weekly_brand"]),
        "brand_mix": _round_numeric(analysis["brand_mix"]),
        "intent_mix": _round_numeric(analysis["intent_mix"]),
        "theme_mix": _round_numeric(analysis["theme_mix"]),
        "landing_pages": _round_numeric(analysis["landing_pages"][:15]),
        "opportunities": _round_numeric(analysis["opportunities"]),
        "data_quality": quality_rows,
    }
    return {"surface": "report", "manifest": manifest, "snapshot": {"version": 1, "generatedAt": analysis["generated_at"], "status": "ready", "datasets": datasets}, "sources": [gsc_source, website_source]}


def save_json(path: str | Path, payload: dict) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
