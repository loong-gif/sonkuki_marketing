#!/usr/bin/env python3
"""Backfill the SCD_Raw Link fields to Page_Summary and Query_Summary.

The raw text columns keep the legacy column names ``page`` and ``query`` at
the database layer, so this script deliberately writes the generated hidden
ForeignKey columns instead of the Link titles.  This avoids an ambiguous API
field-name resolution that can otherwise turn a Python dict into the text
literal ``[object Object]``.
"""

import argparse
import glob
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
SCD_TABLE_ID = "mfbg6s0mv9l74ky"
PAGE_TABLE_ID = "m0fl1tcxyopz1s3"
QUERY_TABLE_ID = "muav8zitnoqlauu"
PAGE_FK_FIELD = "nc_igzh___Page_Summary_id"
QUERY_FK_FIELD = "nc_igzh___Query_Summary_id"
ROOT = Path(__file__).resolve().parents[1]


def credential_value(label: str) -> str:
    for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith(label + ":"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"Missing credential: {label}")


TOKEN = credential_value("NocoDB PAT")
OPENER = build_opener(ProxyHandler({}))


def request(method: str, path: str, payload=None, retries: int = 6):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        try:
            with OPENER.open(Request(API + path, data=body, method=method, headers=headers), timeout=90) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB request failed: {method} {path}: {last}")


def list_records(table_id: str, fields: list[str]) -> list[dict]:
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset, "fields": ",".join(fields)}
        payload = request("GET", f"/api/v2/tables/{table_id}/records?{urlencode(params)}")
        batch = payload.get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def load_snapshot() -> list[dict]:
    rows = []
    files = sorted(glob.glob("/private/tmp/scd_plan_*.json"), key=lambda p: int(Path(p).stem.rsplit("_", 1)[1]))
    for filename in files:
        rows.extend(json.loads(Path(filename).read_text(encoding="utf-8"))["list"])
    if len(rows) != 12389:
        raise RuntimeError(f"Unexpected SCD_Raw snapshot size: {len(rows)}")
    return rows


def build_updates() -> tuple[list[dict], dict]:
    pages = list_records(PAGE_TABLE_ID, ["Id", "page_url"])
    queries = list_records(QUERY_TABLE_ID, ["Id", "分组键"])
    page_by_url = {str(row.get("page_url", "")).strip(): row["Id"] for row in pages}
    query_by_key = {str(row.get("分组键", "")).strip(): row["Id"] for row in queries}
    if len(page_by_url) != 242:
        raise RuntimeError(f"Expected 242 unique Page_Summary URLs, got {len(page_by_url)}")
    if len(query_by_key) != 2013:
        raise RuntimeError(f"Expected 2013 unique Query_Summary keys, got {len(query_by_key)}")

    updates = []
    missing_pages = set()
    missing_queries = set()
    for row in load_snapshot():
        page = str(row.get("page", "")).strip()
        query = str(row.get("query", "")).strip()
        page_id = page_by_url.get(page)
        query_id = query_by_key.get(query)
        if page_id is None:
            missing_pages.add(page)
        if query_id is None:
            missing_queries.add(query)
        updates.append({"Id": row["Id"], PAGE_FK_FIELD: page_id, QUERY_FK_FIELD: query_id})
    if missing_pages or missing_queries:
        raise RuntimeError(json.dumps({"missing_pages": sorted(missing_pages), "missing_queries": sorted(missing_queries)}, ensure_ascii=False))
    return updates, {"pages": len(pages), "queries": len(queries)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="write and verify only SCD_Raw Id=1")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    updates, dimensions = build_updates()
    if args.test:
        updates = [item for item in updates if item["Id"] == 1]
        if not updates:
            raise RuntimeError("Snapshot does not contain SCD_Raw Id=1")
    for start in range(0, len(updates), args.batch_size):
        batch = updates[start : start + args.batch_size]
        request("PATCH", f"/api/v2/tables/{SCD_TABLE_ID}/records", batch)
        print(f"updated relation keys {min(start + args.batch_size, len(updates))}/{len(updates)}", flush=True)
    # Request hidden FK fields only here.  Asking the v2 API to expand both
    # Link fields can recurse through the generated reverse relations and make
    # this otherwise small verification response very slow.
    row = list_records(SCD_TABLE_ID, ["Id", "page_raw", "query_raw", PAGE_FK_FIELD, QUERY_FK_FIELD])[0]
    print(json.dumps({"dimensions": dimensions, "row1": row, "updated": len(updates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
