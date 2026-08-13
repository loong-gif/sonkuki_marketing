#!/usr/bin/env python3
"""Upsert Home Depot product dataset into NocoDB competitor_product table.

Usage:
  python3 scripts/upload_competitor_products.py [--dry-run]

Direct connection only (NocoDB host not reachable via the configured proxy).
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = ROOT / "credentials.txt"
SOURCE = Path("/Users/wyl/Downloads/dataset_e-commerce-scraping-tool_2026-08-12_14-44-54-059.json")
TABLE_ID = "m0vk08vypm4jrl7"   # competitor_product
API_ROOT = "http://72.52.161.65:8080"

TOKEN = next(
    line.split(":", 1)[1].strip()
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines()
    if line.startswith("NocoDB PAT:")
)
OPENER = build_opener(ProxyHandler({}))

# column -> JSON path (list = nested lookup). Only fields with source data.
MAPPING = {
    "itemId": ["additionalProperties", "parentId"],
    "mpn": ["mpn"],
    "name": ["name"],
    "salePrice": ["offers", "price"],
    "originalPrice": ["additionalProperties", "originalPrice"],
    "offers|priceCurrency": ["offers", "priceCurrency"],
    "url": ["url"],
    "brand|slogan": ["brand", "slogan"],
    "description": ["description"],
    "image": ["image"],
    "rating": ["rating"],
    "reviewCount": ["reviewCount"],
    "isSuperSku": ["additionalProperties", "isSuperSku"],
    "parentId": ["additionalProperties", "parentId"],
    "quantityLimit": ["additionalProperties", "quantityLimit"],
    "returnable": ["additionalProperties", "returnable"],
    "savings": ["additionalProperties", "savings"],
    "savingsPercent": ["additionalProperties", "savingsPercent"],
    "storeSkuNumber": ["additionalProperties", "storeSkuNumber"],
    "totalReviews": ["additionalProperties", "totalReviews"],
    "totalVariants": ["additionalProperties", "totalVariants"],
}


def request(method, path, payload=None, retries=5, timeout=90):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            response = OPENER.open(Request(API_ROOT + path, data=body, headers=headers, method=method), timeout=timeout)
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionResetError, ConnectionError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"NocoDB request failed: {method} {path}: {exc}") from exc
            time.sleep(2 ** attempt)


def table_columns():
    meta = request("GET", f"/api/v2/meta/tables/{TABLE_ID}")
    return {c["title"] for c in meta.get("columns", [])}


def existing_rows():
    rows, offset = [], 0
    while True:
        params = urlencode({"limit": 1000, "offset": offset, "fields": "Id,url"})
        batch = request("GET", f"/api/v2/tables/{TABLE_ID}/records?{params}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def map_record(rec, valid_cols):
    def get(path):
        node = rec
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    row = {}
    for col, path in MAPPING.items():
        if col in valid_cols:
            row[col] = get(path)
    # dynamic specification columns (only if the target column exists)
    specs = rec.get("additionalProperties", {}).get("specifications") or {}
    for key, value in specs.items():
        col = f"specifications|{key}"
        if col in valid_cols:
            row[col] = value
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    valid_cols = table_columns()
    mapped = [map_record(r, valid_cols) for r in data]

    existing = existing_rows()
    url_to_id = {str(r.get("url", "")).rstrip("/"): r["Id"] for r in existing if r.get("url")}

    inserts, updates = [], []
    for row in mapped:
        key = str(row.get("url") or "").rstrip("/")
        if key in url_to_id:
            row["Id"] = url_to_id[key]
            updates.append(row)
        else:
            inserts.append(row)

    print(json.dumps({"insert": len(inserts), "update": len(updates), "total": len(mapped)},
                     ensure_ascii=False))
    for sample in (inserts[:1] + updates[:1]):
        print("SAMPLE", json.dumps({k: v for k, v in sample.items() if k != "Id"},
                                   ensure_ascii=False)[:400])

    if args.dry_run:
        return

    for start in range(0, len(inserts), 20):
        request("POST", f"/api/v2/tables/{TABLE_ID}/records", inserts[start:start + 20])
    for start in range(0, len(updates), 20):
        request("PATCH", f"/api/v2/tables/{TABLE_ID}/records", updates[start:start + 20])
    print(f"done: {len(inserts)} inserted, {len(updates)} updated")


if __name__ == "__main__":
    sys.exit(main())
