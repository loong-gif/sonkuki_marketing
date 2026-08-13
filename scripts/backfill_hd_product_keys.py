#!/usr/bin/env python3
"""Backfill homedepot_product.product_key from the HD<->SF mpn tracker so
homedepot_product joins page_product on product_key.

product_key = "PRODUCT:SONKUKI:" + normalized sf_sku (from tracker).
"""

import csv
import json
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
TRACKER = ROOT / "inputs" / "homedepot_sf_mpn_tracker.tsv"
HD_TABLE = "mnttfzrhu6gp6s0"
PP_TABLE = "ma3331finostkis"
PREFIX = "PRODUCT:SONKUKI:"
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


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


def all_records(table_id, fields):
    rows, offset = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": offset, "fields": ",".join(fields)})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def main():
    # load tracker
    hd_to_sf = {}
    with open(TRACKER, encoding="utf-8") as f:
        rd = csv.reader(f, delimiter="\t")
        next(rd)
        for row in rd:
            if row and row[0].strip() and row[1].strip():
                hd_to_sf[row[0].strip().upper()] = row[1].strip().upper()
    print(f"tracker mappings: {len(hd_to_sf)}", flush=True)

    # load homedepot rows
    rows = all_records(HD_TABLE, ["Id", "mpn", "product_key"])
    patches = []
    for r in rows:
        mpn = str(r.get("mpn") or "").strip().upper()
        if mpn not in hd_to_sf:
            continue
        key = PREFIX + hd_to_sf[mpn]
        if str(r.get("product_key") or "") != key:
            patches.append({"Id": r["Id"], "product_key": key})
    print(f"homedepot rows to update: {len(patches)}", flush=True)

    for start in range(0, len(patches), 50):
        request("PATCH", f"/api/v2/tables/{HD_TABLE}/records", patches[start:start + 50])
    print(f"patched {len(patches)} rows", flush=True)

    # validate join
    hp = all_records(HD_TABLE, ["Id", "mpn", "product_key"])
    pp = all_records(PP_TABLE, ["Id", "mpn", "product_key"])
    hp_keys = {r["product_key"] for r in hp if r.get("product_key")}
    pp_keys = {r["product_key"] for r in pp if r.get("product_key")}
    joined = hp_keys & pp_keys
    print(f"join by product_key: {len(joined)}", flush=True)
    for k in sorted(joined)[:5]:
        hp_row = next(r for r in hp if r.get("product_key") == k)
        pp_row = next(r for r in pp if r.get("product_key") == k)
        print(f"  {k}: HD mpn={hp_row.get('mpn')} <-> SF mpn={pp_row.get('mpn')}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
