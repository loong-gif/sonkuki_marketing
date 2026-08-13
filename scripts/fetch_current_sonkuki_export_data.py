#!/usr/bin/env python3
"""Fetch the current Sonkuki NocoDB tables for local XLSX export."""

import json
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
BASE_ID = "p447va1t8jqqjty"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("/private/tmp/sonkuki_current_export_data.json")
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(6):
        try:
            with OPENER.open(Request(API + path, data=body, method=method, headers=headers), timeout=90) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected) as exc:
            last = exc
            if attempt + 1 < 6:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB request failed: {method} {path}: {last}")


def records(table_id, fields):
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset, "fields": ",".join(fields)}
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{urlencode(params)}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def table_list():
    payload = request("GET", f"/api/v2/meta/bases/{BASE_ID}/tables")
    return payload.get("list", [])


def main():
    tables = table_list()
    by_title = {table.get("title"): table.get("id") for table in tables}
    required = {
        "SCD_Raw": "mfbg6s0mv9l74ky",
        "Page_Summary": "m0fl1tcxyopz1s3",
        "Query_Summary": "muav8zitnoqlauu",
    }
    # The legacy API no longer exposes the preserved text aliases after the
    # Link fields were created.  Read the live business fields and foreign
    # keys, then resolve the page/query labels from the dimension tables.
    scd_fields = ["Id", "date", "clicks", "impressions", "ctr", "position", "nc_igzh___Page_Summary_id", "nc_igzh___Query_Summary_id"]
    page_fields = ["Id", "CreatedAt", "UpdatedAt", "Id1", "page_url", "Rows", "Clicks", "Impressions", "CTR", "Weighted_Avg_Position", "Queries"]
    query_fields = ["Id", "CreatedAt", "UpdatedAt", "分组键", "Rows", "Clicks", "Impressions", "CTR", "Weighted_Avg_Position", "Pages"]
    pages = records(required["Page_Summary"], page_fields)
    queries = records(required["Query_Summary"], query_fields)
    page_by_id = {row.get("Id"): row.get("page_url") for row in pages}
    query_by_id = {row.get("Id"): row.get("分组键") for row in queries}
    scd_rows = records(required["SCD_Raw"], scd_fields)
    for row in scd_rows:
        page_id = row.pop("nc_igzh___Page_Summary_id", None)
        query_id = row.pop("nc_igzh___Query_Summary_id", None)
        row["page_id"] = page_id
        row["page_url"] = page_by_id.get(page_id)
        row["query_id"] = query_id
        row["query"] = query_by_id.get(query_id)
    data = {
        "tables": {**required, "Date_Summary": by_title.get("Date_Summary")},
        "scd": scd_rows,
        "pages": pages,
        "queries": queries,
        "date_summary": [],
    }
    date_id = by_title.get("Date_Summary")
    if date_id:
        date_meta = request("GET", f"/api/v2/meta/tables/{date_id}")
        date_fields = [column.get("title") for column in date_meta.get("columns", []) if column.get("title")]
        data["date_summary"] = records(date_id, date_fields)
        data["date_fields"] = date_fields
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "scd": len(data["scd"]), "pages": len(data["pages"]), "queries": len(data["queries"]), "date_summary": len(data["date_summary"]), "date_table_found": bool(date_id)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
