#!/usr/bin/env python3
import glob
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
SCD_TABLE_ID = "mfbg6s0mv9l74ky"
PAGE_TABLE_ID = "mk6mn7cbxl1eu1f"
PAGE_FK_FIELD = "nc_igzh___Page_id"
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
    raise RuntimeError(f"request failed: {method} {path}: {last}")

def list_records(table_id, fields):
    rows = []
    offset = 0
    while True:
        payload = request("GET", f"/api/v2/tables/{table_id}/records?{urlencode({'limit': 1000, 'offset': offset, 'fields': ','.join(fields)})}")
        batch = payload.get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)

page_rows = list_records(PAGE_TABLE_ID, ["Id", "page_url"])
page_by_url = {str(row["page_url"]).strip(): row["Id"] for row in page_rows}
raw_rows = []
for filename in sorted(glob.glob("/private/tmp/scd_plan_*.json"), key=lambda p: int(Path(p).stem.rsplit("_", 1)[1])):
    raw_rows.extend(json.loads(Path(filename).read_text(encoding="utf-8"))["list"])
updates = []
for row in raw_rows:
    url = str(row.get("page", "")).strip()
    page_id = page_by_url.get(url)
    if page_id is None:
        raise RuntimeError(f"unmatched page: {url}")
    updates.append({"Id": row["Id"], PAGE_FK_FIELD: page_id})

for start in range(0, len(updates), 20):
    request("PATCH", f"/api/v2/tables/{SCD_TABLE_ID}/records", updates[start:start + 20])
    print(f"updated page links {min(start + 20, len(updates))}/{len(updates)}", flush=True)

print(json.dumps({"scd_rows": len(updates), "page_rows": len(page_rows), "unique_page_ids": len(set(item[PAGE_FK_FIELD] for item in updates))}, ensure_ascii=False))
