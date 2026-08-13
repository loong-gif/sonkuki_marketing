#!/usr/bin/env python3
"""Inspect Query_Summary CTR population without changing the database."""

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
TABLE_ID = "muav8zitnoqlauu"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def get(path):
    req = Request(API + path, headers={"xc-token": TOKEN, "accept": "application/json"})
    with OPENER.open(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    meta = get(f"/api/v2/meta/tables/{TABLE_ID}")
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset, "fields": "Id,分组键,Clicks,Impressions,CTR"}
        batch = get(f"/api/v2/tables/{TABLE_ID}/records?{urlencode(params)}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += len(batch)
    nonempty = [row for row in rows if row.get("CTR") not in (None, "")]
    calculable = [row for row in rows if float(row.get("Impressions") or 0) > 0]
    expected = [float(row.get("Clicks") or 0) / float(row.get("Impressions") or 0) for row in calculable]
    ctr_column = next(column for column in meta.get("columns", []) if column.get("title") == "CTR")
    print(json.dumps({
        "rows": len(rows),
        "ctr_nonempty": len(nonempty),
        "ctr_empty": len(rows) - len(nonempty),
        "ctr_column": {"uidt": ctr_column.get("uidt"), "dt": ctr_column.get("dt")},
        "calculable_rows": len(calculable),
        "expected_ctr_min": min(expected) if expected else None,
        "expected_ctr_max": max(expected) if expected else None,
        "sample": [{"query": row.get("分组键"), "clicks": row.get("Clicks"), "impressions": row.get("Impressions"), "stored_ctr": row.get("CTR")} for row in rows[:5]],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
