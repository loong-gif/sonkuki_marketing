#!/usr/bin/env python3
"""Hide, but do not delete, the SCD_Raw legacy text backup fields."""

import json
import time
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
TABLE_ID = "mfbg6s0mv9l74ky"
ROOT = Path(__file__).resolve().parents[1]
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


def main():
    meta = request("GET", f"/api/v2/meta/tables/{TABLE_ID}")
    targets = [column for column in meta.get("columns", []) if column.get("title") in {"page_raw", "query_raw"}]
    if {column.get("title") for column in targets} != {"page_raw", "query_raw"}:
        raise RuntimeError("Expected both raw backup fields before hiding them")
    view_id = meta.get("views", [{}])[0].get("id")
    if not view_id:
        raise RuntimeError("SCD_Raw has no default view")
    view_columns = request("GET", f"/api/v1/db/meta/views/{view_id}/columns").get("list", [])
    target_ids = {column["id"]: column["title"] for column in targets}
    target_view_columns = [item for item in view_columns if item.get("fk_column_id") in target_ids]
    if len(target_view_columns) != 2:
        raise RuntimeError("Could not find both raw backup fields in the default view")
    for item in target_view_columns:
        request("PATCH", f"/api/v1/db/meta/views/{view_id}/columns/{item['id']}", {"show": False})
    final_view_columns = request("GET", f"/api/v1/db/meta/views/{view_id}/columns").get("list", [])
    result = {target_ids[item["fk_column_id"]]: item.get("show") for item in final_view_columns if item.get("fk_column_id") in target_ids}
    if result != {"page_raw": False, "query_raw": False}:
        raise RuntimeError(f"Raw backup field hide validation failed: {result}")
    print(json.dumps({"hidden_backup_fields": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
