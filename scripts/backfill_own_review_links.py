#!/usr/bin/env python3
# DEPRECATED: Targets deleted NocoDB table homedepot_products (mnttfzrhu6gp6s0).
# Table removed 2026-08. Do not run — kept for historical reference.
"""Backfill item_id + product_key onto HDV1_Customer_Reviews own rows.

- item_id: from archived sonkuki_reviews_raw (matched by review_key, which is
  derived from itemId|submissionTime|authorId|title) + today's CLI crawl fill.
- product_key: via homedepot_product.product_key (itemId in url -> already
  backfilled from the HD<->SF mpn tracker).
"""

import csv
import hashlib
import json
import re
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
CR_TABLE = "mnz1y5x5kydob4f"        # HDV1_Customer_Reviews
HD_TABLE = "mnttfzrhu6gp6s0"        # homedepot_product
ARCHIVE = ROOT / "outputs" / "sonkuki_reviews_raw_archived_20260813_095913.jsonl"
FILL = Path("/tmp/hd_own_fill.json")
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


def key_from_parts(parts):
    src = "|".join(str(x) for x in parts)
    return "HOME_DEPOT:OWN:" + hashlib.sha1(src.encode("utf-8")).hexdigest()[:20]


def main():
    if not wait_server_up():
        print("server down", flush=True)
        sys.exit(1)

    # 1. review_key -> itemId from archive
    key_to_item = {}
    for line in open(ARCHIVE, encoding="utf-8"):
        r = json.loads(line)
        k = key_from_parts([r.get("itemId"), r.get("submissionTime"), r.get("authorId"), r.get("title")])
        if r.get("itemId"):
            key_to_item[k] = str(r["itemId"])
    # from today's fill
    if FILL.exists():
        for it in json.loads(FILL.read_text(encoding="utf-8")):
            if it.get("statusMessage") != "FOUND" or not it.get("id"):
                continue
            k = key_from_parts([it.get("itemId"), it.get("submissionTime"), it.get("authorId"), it.get("title")])
            if it.get("itemId"):
                key_to_item[k] = str(it["itemId"])
    print(f"key->itemId map: {len(key_to_item)}", flush=True)

    # 2. homedepot_product: itemId (from url) -> product_key
    hd_rows = all_records(HD_TABLE, ["Id", "mpn", "url", "product_key"])
    def item_id(url):
        m = re.search(r"/(\d{6,})/?$", str(url or "").rstrip("/"))
        return m.group(1) if m else None
    item_to_product_key = {}
    for r in hd_rows:
        iid = item_id(r.get("url"))
        if iid and r.get("product_key"):
            item_to_product_key[iid] = r["product_key"]
    print(f"itemId->product_key map: {len(item_to_product_key)}", flush=True)

    # 3. add columns
    meta = request("GET", f"/api/v2/meta/tables/{CR_TABLE}")
    cols = {c["title"] for c in meta.get("columns", [])}
    for col in ("item_id", "product_key"):
        if col not in cols:
            request("POST", f"/api/v2/meta/tables/{CR_TABLE}/columns", {"title": col, "uidt": "SingleLineText"})
            print(f"column {col} created", flush=True)
            time.sleep(15)
            if not wait_server_up():
                print("server down after column add; abort", flush=True)
                sys.exit(1)
        else:
            print(f"column {col} already exists", flush=True)

    # 4. backfill own rows
    own = [r for r in all_records(CR_TABLE, ["Id", "review_key", "item_id", "product_key"]) if str(r.get("review_key", "")).startswith("HOME_DEPOT:OWN:")]
    print(f"own rows: {len(own)}", flush=True)
    patches = []
    for r in own:
        k = r["review_key"]
        item = key_to_item.get(k)
        pk = item_to_product_key.get(item) if item else None
        if (item and str(r.get("item_id") or "") != item) or (pk and str(r.get("product_key") or "") != pk):
            up = {}
            if item and str(r.get("item_id") or "") != item:
                up["item_id"] = item
            if pk and str(r.get("product_key") or "") != pk:
                up["product_key"] = pk
            patches.append({"Id": r["Id"], **up})
    print(f"rows to patch: {len(patches)}", flush=True)
    for start in range(0, len(patches), 50):
        request("PATCH", f"/api/v2/tables/{CR_TABLE}/records", patches[start:start + 50])
    print(f"patched {len(patches)}", flush=True)

    # 5. verify
    check = all_records(CR_TABLE, ["Id", "review_key", "item_id", "product_key"])
    own2 = [r for r in check if str(r.get("review_key", "")).startswith("HOME_DEPOT:OWN:")]
    with_item = sum(1 for r in own2 if r.get("item_id"))
    with_pk = sum(1 for r in own2 if r.get("product_key"))
    print(f"verify: own={len(own2)}, with item_id={with_item}, with product_key={with_pk}", flush=True)
    for r in own2[:3]:
        print("  sample:", r.get("review_key")[:30], "item_id=", r.get("item_id"), "product_key=", r.get("product_key"), flush=True)


if __name__ == "__main__":
    sys.exit(main())
