#!/usr/bin/env python3
"""Export all tables of the Sonkuki NocoDB base into a single XLSX file.

One sheet per table, columns in NocoDB column order (internal nc_* columns
skipped). Cell values are kept as strings/numbers; nested dict/list values are
JSON-serialized.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

from openpyxl import Workbook

API = "http://72.52.161.65:8080"
BASE_ID = "p447va1t8jqqjty"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs"
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))

SKIP_COLS = {"nc_created_by", "nc_updated_by", "nc_order", "__nc_deleted"}
SKIP_TABLES = {"gsc_raw"}  # user preference: raw GSC table not needed in exports (was gsc_data_raw)


def request(method, path, retries=6):
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, headers=headers, method=method), timeout=120)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"NocoDB request failed: {method} {path}: {exc}") from exc
            time.sleep(min(30, 2 ** attempt))


def list_tables():
    return request("GET", f"/api/v1/db/meta/projects/{BASE_ID}/tables").get("list", [])


def table_meta(table_id):
    return request("GET", f"/api/v2/meta/tables/{table_id}")


def all_records(table_id):
    rows, offset = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": offset})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def sheet_name(title):
    clean = "".join(c if c not in "[]:*?/\\" else "_" for c in title)
    return (clean[:31] or "Sheet")


def cell_value(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def main():
    tables = list_tables()
    print(f"tables: {len(tables)}", flush=True)

    wb = Workbook(write_only=True)
    total_rows = 0
    for t in tables:
        title = t["title"]
        if title in SKIP_TABLES:
            print(f"  SKIP {title} (user preference)", flush=True)
            continue
        tid = t["id"]
        meta = table_meta(tid)
        cols = [c["title"] for c in meta.get("columns", []) if c["title"] not in SKIP_COLS]
        rows = all_records(tid)
        ws = wb.create_sheet(title=sheet_name(title))
        ws.append(cols)
        for row in rows:
            ws.append([cell_value(row.get(c, "")) for c in cols])
        total_rows += len(rows)
        print(f"  {title}: {len(rows)} rows, {len(cols)} cols", flush=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"sonkuki_all_tables_{stamp}.xlsx"
    wb.save(out)
    print(f"saved {out} ({total_rows} data rows, {len(tables)} sheets)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
