#!/usr/bin/env python3
"""Extend Page into the page-grain summary dimension and backfill metrics."""

import glob
import json
import time
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
PAGE_TABLE_ID = "mk6mn7cbxl1eu1f"
token = next(line.split(":", 1)[1].strip() for line in open("credentials.txt", encoding="utf-8") if line.startswith("NocoDB PAT:"))
opener = build_opener(ProxyHandler({}))


def request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": token, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(6):
        try:
            with opener.open(Request(API + path, data=body, method=method, headers=headers), timeout=90) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB request failed: {method} {path}: {last}")


def load_scd_rows():
    rows = []
    for filename in sorted(glob.glob("/private/tmp/scd_plan_*.json"), key=lambda p: int(Path(p).stem.rsplit("_", 1)[1])):
        rows.extend(json.loads(Path(filename).read_text(encoding="utf-8"))["list"])
    if len(rows) != 12389:
        raise RuntimeError(f"Unexpected SCD_Raw snapshot size: {len(rows)}")
    return rows


def aggregate(rows):
    stats = defaultdict(lambda: {"Rows": 0, "Clicks": 0, "Impressions": 0, "PositionWeight": 0.0, "Queries": set()})
    for row in rows:
        page = str(row.get("page", "")).strip()
        if not page:
            raise RuntimeError(f"Blank page in SCD_Raw row {row.get('Id')}")
        clicks = float(row.get("clicks") or 0)
        impressions = float(row.get("impressions") or 0)
        position = float(row.get("position") or 0)
        bucket = stats[page]
        bucket["Rows"] += 1
        bucket["Clicks"] += clicks
        bucket["Impressions"] += impressions
        bucket["PositionWeight"] += position * impressions
        bucket["Queries"].add(str(row.get("query", "")).strip())
    return {
        page: {
            "Rows": int(values["Rows"]),
            "Clicks": int(values["Clicks"]),
            "Impressions": int(values["Impressions"]),
            "CTR": (values["Clicks"] / values["Impressions"]) if values["Impressions"] else 0,
            "Weighted_Avg_Position": (values["PositionWeight"] / values["Impressions"]) if values["Impressions"] else 0,
            "Queries": len(values["Queries"] - {""}),
        }
        for page, values in stats.items()
    }


def ensure_columns():
    meta = request("GET", f"/api/v2/meta/tables/{PAGE_TABLE_ID}")
    present = {column["title"] for column in meta.get("columns", [])}
    definitions = [
        ("Rows", "Number"),
        ("Clicks", "Number"),
        ("Impressions", "Number"),
        ("CTR", "Decimal"),
        ("Weighted_Avg_Position", "Decimal"),
        ("Queries", "Number"),
    ]
    for title, uidt in definitions:
        if title not in present:
            request("POST", f"/api/v1/db/meta/tables/{PAGE_TABLE_ID}/columns", {"title": title, "column_name": title, "uidt": uidt})
            print(f"created Page.{title}", flush=True)
    return request("GET", f"/api/v2/meta/tables/{PAGE_TABLE_ID}")


def list_pages():
    rows = []
    offset = 0
    while True:
        payload = request("GET", f"/api/v2/tables/{PAGE_TABLE_ID}/records?{urlencode({'limit': 1000, 'offset': offset, 'fields': 'Id,page_url'})}")
        batch = payload.get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


stats = aggregate(load_scd_rows())
ensure_columns()
pages = list_pages()
updates = []
for page in pages:
    url = str(page.get("page_url", "")).strip()
    if url not in stats:
        raise RuntimeError(f"Page table contains an unmatched URL: {url}")
    updates.append({"Id": page["Id"], **stats[url]})
if len(updates) != 242:
    raise RuntimeError(f"Expected 242 Page rows, got {len(updates)}")
for start in range(0, len(updates), 10):
    request("PATCH", f"/api/v2/tables/{PAGE_TABLE_ID}/records", updates[start : start + 10])
    print(f"updated Page summary {min(start + 10, len(updates))}/{len(updates)}", flush=True)
print(json.dumps({"pages": len(updates), "scd_rows": 12389, "summary_fields": ["Rows", "Clicks", "Impressions", "CTR", "Weighted_Avg_Position", "Queries"]}, ensure_ascii=False))
