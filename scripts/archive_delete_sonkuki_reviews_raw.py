#!/usr/bin/env python3
"""Backup sonkuki_reviews_raw (mhejqhev6vgfkhz) to outputs/ then delete the table.

HDV1_Customer_Reviews already holds the same 4,966 own reviews (core fields);
the extra raw fields (photos/badges/contextDataValues/...) have no analytical
value per user decision. Backup is kept for safety.
"""

import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs"
TABLE = "mhejqhev6vgfkhz"        # sonkuki_reviews_raw
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def request(method, path, payload=None, retries=8, timeout=120):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, data=body, headers=headers, method=method), timeout=timeout)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, ConnectionResetError, socket.timeout, OSError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"failed {method} {path}: {exc}") from exc
            time.sleep(min(20, 2 ** attempt))


def all_records(table_id):
    rows, offset = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": offset})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def main():
    rows = all_records(TABLE)
    print(f"loaded {len(rows)} rows", flush=True)
    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = OUT_DIR / f"sonkuki_reviews_raw_archived_{stamp}.jsonl"
    with open(backup, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"backup -> {backup}", flush=True)

    request("DELETE", f"/api/v2/meta/tables/{TABLE}")
    print("table deleted", flush=True)

    tables = request("GET", "/api/v1/db/meta/projects/p447va1t8jqqjty/tables")["list"]
    titles = [t["title"] for t in tables]
    print(f"tables now: {len(titles)}", flush=True)
    print(f"sonkuki_reviews_raw gone: {TABLE not in [t['id'] for t in tables]}", flush=True)

    # check page_product link column state
    pp = request("GET", "/api/v2/meta/tables/ma3331finostkis")
    for c in pp.get("columns", []):
        if c["title"] in ("product_link",) or c.get("uidt") in ("LinkToAnotherRecord", "Links"):
            print(f"page_product.{c['title']}: uidt={c.get('uidt')} related={c.get('colOptions', {}).get('fk_related_model_id')}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
