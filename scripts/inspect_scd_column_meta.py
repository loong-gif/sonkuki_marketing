#!/usr/bin/env python3
import json
import time
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
TABLE_ID = "mfbg6s0mv9l74ky"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
opener = build_opener(ProxyHandler({}))
for attempt in range(6):
    try:
        req = Request(API + f"/api/v2/meta/tables/{TABLE_ID}", headers={"xc-token": TOKEN, "accept": "application/json"})
        with opener.open(req, timeout=90) as response:
            meta = json.loads(response.read().decode("utf-8"))
        break
    except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected):
        if attempt == 5:
            raise
        time.sleep(2 ** attempt)
for column in meta.get("columns", []):
    if column.get("title") in {"page_raw", "query_raw"}:
        print(json.dumps(column, ensure_ascii=False))
print(json.dumps({"column_titles": [(column.get("title"), column.get("column_name"), column.get("uidt")) for column in meta.get("columns", [])], "top_level_keys": sorted(meta.keys()), "views": meta.get("views")}, ensure_ascii=False))
view_id = meta.get("views", [{}])[0].get("id")
if view_id:
    try:
        view_req = Request(API + f"/api/v1/db/meta/views/{view_id}/columns", headers={"xc-token": TOKEN, "accept": "application/json"})
        with opener.open(view_req, timeout=90) as response:
            print(json.dumps({"view_columns": json.loads(response.read().decode("utf-8"))}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"view_columns_error": type(exc).__name__}, ensure_ascii=False))
