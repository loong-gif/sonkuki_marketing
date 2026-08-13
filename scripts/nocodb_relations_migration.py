#!/usr/bin/env python3
"""Idempotent Sonkuki NocoDB relation migration helper.

Network access intentionally bypasses inherited proxy settings because the
NocoDB host is reachable directly while the configured proxy is not.
"""

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = ROOT / "credentials.txt"
BASE_ID = "p447va1t8jqqjty"
SCD_TABLE_ID = "mfbg6s0mv9l74ky"
API_ROOT = "http://72.52.161.65:8080"


def credential_value(label):
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
        if line.startswith(label + ":"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"Missing credential: {label}")


TOKEN = credential_value("NocoDB PAT")
OPENER = build_opener(ProxyHandler({}))


def request(method, path, payload=None, retries=5):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            response = OPENER.open(Request(API_ROOT + path, data=body, headers=headers, method=method), timeout=90)
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionResetError, ConnectionError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"NocoDB request failed: {method} {path}: {exc}") from exc
            time.sleep(2 ** attempt)


def list_tables():
    return request("GET", f"/api/v1/db/meta/projects/{BASE_ID}/tables").get("list", [])


def table_meta(table_id):
    return request("GET", f"/api/v2/meta/tables/{table_id}")


def list_records(table_id, fields=None):
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset}
        if fields:
            params["fields"] = ",".join(fields)
        payload = request("GET", f"/api/v2/tables/{table_id}/records?{urlencode(params)}")
        batch = payload.get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def insert_batches(table_id, rows, batch_size=20):
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        request("POST", f"/api/v2/tables/{table_id}/records", batch)
        print(f"inserted {min(start + batch_size, len(rows))}/{len(rows)}", flush=True)


def ensure_page_rows():
    page_table = next((table for table in list_tables() if table.get("title") == "Page"), None)
    if not page_table:
        raise RuntimeError("Page table does not exist; create it before running this helper")
    page_table_id = page_table["id"]
    scd_rows = list_records(SCD_TABLE_ID, ["Id", "page_raw"])
    existing = list_records(page_table_id, ["Id", "page_url"])
    existing_by_url = {str(row.get("page_url", "")).strip(): row["Id"] for row in existing if row.get("page_url")}
    urls = sorted({str(row.get("page_raw", "")).strip() for row in scd_rows if row.get("page_raw")})
    missing = [{"page_url": url} for url in urls if url not in existing_by_url]
    if missing:
        insert_batches(page_table_id, missing)
        existing = list_records(page_table_id, ["Id", "page_url"])
        existing_by_url = {str(row.get("page_url", "")).strip(): row["Id"] for row in existing if row.get("page_url")}
    if len(existing_by_url) != len(urls):
        raise RuntimeError(f"Page key validation failed: expected {len(urls)}, got {len(existing_by_url)}")
    print(json.dumps({"page_table_id": page_table_id, "scd_rows": len(scd_rows), "unique_pages": len(urls), "page_rows": len(existing_by_url)}, ensure_ascii=False))
    return page_table_id, existing_by_url


if __name__ == "__main__":
    if sys.argv[1:] != ["--pages-only"]:
        raise SystemExit("usage: nocodb_relations_migration.py --pages-only")
    ensure_page_rows()
