#!/usr/bin/env python3
"""Derive four keyword-report datasets from the existing SCD_Raw snapshot."""

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sonkuki_gsc_analysis import classify_brand, normalize_query


OUTPUT = Path("/private/tmp/sonkuki_keyword_report_generated.json")


def load_rows():
    rows = []
    for filename in sorted(glob.glob("/private/tmp/scd_plan_*.json"), key=lambda p: int(Path(p).stem.rsplit("_", 1)[1])):
        rows.extend(json.loads(Path(filename).read_text(encoding="utf-8"))["list"])
    if len(rows) != 12389:
        raise RuntimeError(f"Expected 12389 SCD_Raw rows, got {len(rows)}")
    return rows


def main():
    source = load_rows()
    site_url = "sc-domain:sonkuki.com"
    domain = "https://sonkuki.com/"
    daily_query = defaultdict(lambda: {"clicks": 0, "impressions": 0, "weighted": 0.0})
    monthly = defaultdict(lambda: {"clicks": 0, "impressions": 0, "weighted": 0.0, "rows": 0})
    for row in source:
        date = str(row["date"])
        query = str(row.get("query", "")).strip()
        clicks = int(row.get("clicks") or 0)
        impressions = int(row.get("impressions") or 0)
        position = float(row.get("position") or 0)
        daily = daily_query[(date, query)]
        daily["clicks"] += clicks
        daily["impressions"] += impressions
        daily["weighted"] += position * impressions
        month = date[:7] + "-01"
        bucket = monthly[(month, query)]
        bucket["clicks"] += clicks
        bucket["impressions"] += impressions
        bucket["weighted"] += position * impressions
        bucket["rows"] += 1

    research = []
    for row in source:
        date = str(row["date"])
        query = str(row.get("query", "")).strip()
        clicks = int(row.get("clicks") or 0)
        impressions = int(row.get("impressions") or 0)
        position = float(row.get("position") or 0)
        daily = daily_query[(date, query)]
        research.append({
            "date": date,
            "site_url": site_url,
            "page": str(row.get("page", "")).strip(),
            "query": query,
            "branded_type": classify_brand(query),
            "clicks": clicks,
            "impressions": impressions,
            "positions_tmp": position * impressions,
            "total_clicks_all_pages": daily["clicks"],
            "total_impressions_all_pages": daily["impressions"],
            "positions_tmp_all_pages": daily["weighted"],
        })
    research.sort(key=lambda row: (row["date"], row["query"], row["page"]))

    monthly_rows = []
    for (month, query), bucket in monthly.items():
        monthly_rows.append({
            "month": month,
            "domain": domain,
            "query": query,
            "impressions": bucket["impressions"],
            "clicks": bucket["clicks"],
            "impression_tmp": bucket["weighted"],
            "avg_position": bucket["weighted"] / bucket["impressions"] if bucket["impressions"] else 0.0,
        })
    monthly_rows.sort(key=lambda row: (row["month"], -row["impressions"], row["query"]))

    months = sorted({row["month"] for row in monthly_rows})
    latest = months[-1]
    previous = months[-2] if len(months) > 1 else None
    current_by_query = {row["query"]: row for row in monthly_rows if row["month"] == latest}
    previous_by_query = {row["query"]: row for row in monthly_rows if row["month"] == previous} if previous else {}
    improved = [
        {key: current[key] for key in ("query", "domain", "month", "avg_position", "impressions", "clicks")}
        for query, current in current_by_query.items()
        if query in previous_by_query and current["avg_position"] < previous_by_query[query]["avg_position"]
    ]
    improved.sort(key=lambda row: (row["avg_position"], -row["impressions"], row["query"]))
    newly_ranked = [
        {key: current[key] for key in ("query", "month", "domain", "impressions", "clicks", "avg_position")}
        for query, current in current_by_query.items()
        if query not in previous_by_query
    ]
    newly_ranked.sort(key=lambda row: (-row["impressions"], row["avg_position"], row["query"]))

    output = {
        "source_rows": len(source),
        "site_url": site_url,
        "domain": domain,
        "date_min": min(str(row["date"]) for row in source),
        "date_max": max(str(row["date"]) for row in source),
        "months": months,
        "latest_month": latest,
        "previous_month": previous,
        "reports": {
            "gsc_keyword_research": {"columns": list(research[0]) if research else [], "rows": research},
            "gsc_keyword_month": {"columns": list(monthly_rows[0]) if monthly_rows else [], "rows": monthly_rows},
            "gsc_keyword_improved": {"columns": ["query", "domain", "month", "avg_position", "impressions", "clicks"], "rows": improved},
            "gsc_keyword_newly_ranked": {"columns": ["query", "month", "domain", "impressions", "clicks", "avg_position"], "rows": newly_ranked},
        },
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "source_rows": len(source), "months": months, "report_rows": {name: len(data["rows"]) for name, data in output["reports"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
