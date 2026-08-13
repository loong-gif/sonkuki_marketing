#!/usr/bin/env python3
"""Validate the completed SCD_Raw -> Page_Summary/Query_Summary migration."""

import glob
import json
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
SCD = "mfbg6s0mv9l74ky"
PAGE = "m0fl1tcxyopz1s3"
QUERY = "muav8zitnoqlauu"
PAGE_FK = "nc_igzh___Page_Summary_id"
QUERY_FK = "nc_igzh___Query_Summary_id"
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def get(path: str, timeout: int = 90):
    last = None
    for attempt in range(6):
        try:
            req = Request(API + path, headers={"xc-token": TOKEN, "accept": "application/json"})
            with OPENER.open(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected) as exc:
            last = exc
            if attempt + 1 < 6:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB read failed: {path}: {last}")


def records(table_id: str, fields: list[str], limit: int = 1000):
    rows = []
    offset = 0
    while True:
        params = {"limit": limit, "offset": offset, "fields": ",".join(fields)}
        batch = get(f"/api/v2/tables/{table_id}/records?{urlencode(params)}").get("list", [])
        rows.extend(batch)
        if len(batch) < limit:
            return rows
        offset += len(batch)


def snapshot():
    rows = []
    for filename in sorted(glob.glob("/private/tmp/scd_plan_*.json"), key=lambda p: int(Path(p).stem.rsplit("_", 1)[1])):
        rows.extend(json.loads(Path(filename).read_text(encoding="utf-8"))["list"])
    return {row["Id"]: row for row in rows}


def main():
    snap = snapshot()
    pages = records(PAGE, ["Id", "page_url"])
    queries = records(QUERY, ["Id", "分组键"])
    page_by_url = {str(row["page_url"]).strip(): row["Id"] for row in pages}
    query_by_key = {str(row["分组键"]).strip(): row["Id"] for row in queries}
    scd = records(SCD, ["Id", "page_raw", "query_raw", PAGE_FK, QUERY_FK])
    by_id = {row["Id"]: row for row in scd}
    raw_match = sum(1 for row_id, original in snap.items() if by_id.get(row_id, {}).get("page_raw") == original.get("page") and by_id.get(row_id, {}).get("query_raw") == original.get("query"))
    page_fk_match = sum(1 for row_id, original in snap.items() if by_id.get(row_id, {}).get(PAGE_FK) == page_by_url.get(str(original.get("page", "")).strip()))
    query_fk_match = sum(1 for row_id, original in snap.items() if by_id.get(row_id, {}).get(QUERY_FK) == query_by_key.get(str(original.get("query", "")).strip()))
    result = {
        "scd_rows": len(scd),
        "page_summary_rows": len(pages),
        "query_summary_rows": len(queries),
        "unique_page_fks": len({row.get(PAGE_FK) for row in scd}),
        "unique_query_fks": len({row.get(QUERY_FK) for row in scd}),
        "raw_fields_match_snapshot": raw_match,
        "page_fk_match": page_fk_match,
        "query_fk_match": query_fk_match,
        "all_rows_have_page_and_query": all(row.get(PAGE_FK) is not None and row.get(QUERY_FK) is not None for row in scd),
    }
    if result["scd_rows"] != 12389 or result["page_summary_rows"] != 242 or result["query_summary_rows"] != 2013:
        raise SystemExit(json.dumps({"validation_failed": result}, ensure_ascii=False))
    if raw_match != 12389 or page_fk_match != 12389 or query_fk_match != 12389 or not result["all_rows_have_page_and_query"]:
        raise SystemExit(json.dumps({"validation_failed": result}, ensure_ascii=False))
    print(json.dumps({"validation": "passed", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
