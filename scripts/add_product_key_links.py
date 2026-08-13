#!/usr/bin/env python3
"""Task 6 (F7): add normalized product_key to page_product + homedepot_product.

product_key = "PRODUCT:SONKUKI:" + <normalized mpn> (upper, trimmed).
Enables future cross-channel joins (own store <-> Home Depot channel).
"""

import json
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))

TABLES = {
    "page_product": "ma3331finostkis",
    "homedepot_product": "mnttfzrhu6gp6s0",
}
PREFIX = "PRODUCT:SONKUKI:"


def request(method, path, payload=None, timeout=90, retries=8):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, data=body, headers=headers, method=method), timeout=timeout)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, ConnectionResetError, socket.timeout, OSError) as exc:
            last = exc
            time.sleep(min(20, 2 ** attempt))
    raise RuntimeError(f"request failed {method} {path}: {last}")


def server_up():
    try:
        request("GET", "/api/v1/db/meta/projects/p447va1t8jqqjty/tables", timeout=15)
        return True
    except Exception:
        return False


def wait_server_up(max_minutes=10):
    deadline = time.time() + max_minutes * 60
    while time.time() < deadline:
        if server_up():
            return True
        time.sleep(20)
    return False


def all_records(table_id, fields):
    rows, offset = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": offset, "fields": ",".join(fields)})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def table_columns(table_id):
    meta = request("GET", f"/api/v2/meta/tables/{table_id}")
    return {c["title"]: c for c in meta.get("columns", [])}


def main():
    if not wait_server_up():
        print("server down", flush=True)
        sys.exit(1)

    # 1. add product_key column (paced, health-checked)
    for title, tid in TABLES.items():
        cols = table_columns(tid)
        if "product_key" not in cols:
            request("POST", f"/api/v2/meta/tables/{tid}/columns",
                    {"title": "product_key", "uidt": "SingleLineText"}, timeout=90)
            print(f"column product_key created on {title}", flush=True)
            time.sleep(15)
            if not wait_server_up():
                print(f"server down after adding column to {title}; abort", flush=True)
                sys.exit(1)
        else:
            print(f"column product_key already on {title}", flush=True)

    # 2. backfill
    for title, tid in TABLES.items():
        rows = all_records(tid, ["Id", "mpn"])
        patches = []
        for r in rows:
            mpn = str(r.get("mpn") or "").strip().upper()
            if not mpn:
                continue
            key = PREFIX + mpn
            if str(r.get("product_key") or "") != key:
                patches.append({"Id": r["Id"], "product_key": key})
        for start in range(0, len(patches), 50):
            request("PATCH", f"/api/v2/tables/{tid}/records", patches[start:start + 50])
        print(f"backfilled {title}: {len(patches)} rows", flush=True)

    # 3. validate
    pp = all_records(TABLES["page_product"], ["Id", "mpn", "product_key"])
    hp = all_records(TABLES["homedepot_product"], ["Id", "mpn", "product_key"])
    pp_keys = {r.get("product_key") for r in pp if r.get("product_key")}
    hp_keys = {r.get("product_key") for r in hp if r.get("product_key")}
    print(f"page_product: {len(pp)} rows, product_key filled={len(pp_keys)}", flush=True)
    print(f"homedepot_product: {len(hp)} rows, product_key filled={len(hp_keys)}", flush=True)
    overlap = pp_keys & hp_keys
    print(f"cross-channel join by product_key: {len(overlap)}", flush=True)
    print("sample pp keys:", sorted(pp_keys)[:3], flush=True)
    print("sample hp keys:", sorted(hp_keys)[:3], flush=True)


if __name__ == "__main__":
    sys.exit(main())
