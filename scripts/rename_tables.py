#!/usr/bin/env python3
"""Rename tables to normalized snake_case names (paced, health-checked).

Mapping from old title -> new title. NocoDB tables are renamed by PATCHing
the table model (links reference model ids, so link columns survive).
"""

import json
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))

RENAME = {
    "HDV1_Brands": "brands",
    "HDV1_Channel_Listings": "product_listings",
    "HDV1_Customer_Reviews": "reviews",
    "HDV1_Ingestion_Runs": "ingestion_runs",
    "HDV1_Listing_Snapshots": "listing_snapshots",
    "HDV1_Product_Variants": "product_variants",
    "HDV1_Products": "products",
    "HDV1_Raw_Listing_Snapshots": "raw_listing_snapshots",
    "HDV1_Review_Listing_Links": "review_listing_links",
    "HDV1_Source_Registry": "source_registry",
    "page_product": "sonkuki_products",
    "homedepot_product": "homedepot_products",
    "competitor_product": "competitor_products",
    "competitor_product_sale": "competitor_sales",
    "gsc_data_raw": "gsc_raw",
    "gsc_keyword_all-time": "gsc_keyword_all_time",
    "gsc_page_all-time": "gsc_page_all_time",
}


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


def main():
    if not wait_server_up():
        print("server down", flush=True)
        sys.exit(1)

    tables = request("GET", "/api/v1/db/meta/projects/p447va1t8jqqjty/tables")["list"]
    by_title = {t["title"]: t for t in tables}

    for old, new in RENAME.items():
        t = by_title.get(old)
        if not t:
            print(f"SKIP {old}: not found", flush=True)
            continue
        if t["title"] == new:
            print(f"  {old}: already {new}", flush=True)
            continue
        try:
            request("PATCH", f"/api/v2/meta/tables/{t['id']}", {"title": new, "table_name": new}, timeout=90)
            print(f"  {old} -> {new}", flush=True)
        except Exception as exc:
            print(f"  {old} -> FAILED {exc}", flush=True)
        time.sleep(12)
        if not server_up():
            print("  server down -> waiting", flush=True)
            if not wait_server_up():
                print("abort: server down too long", flush=True)
                sys.exit(1)

    # verify
    tables2 = request("GET", "/api/v1/db/meta/projects/p447va1t8jqqjty/tables")["list"]
    titles = sorted(t["title"] for t in tables2)
    print("\nfinal tables:", flush=True)
    for t in titles:
        print("  ", t, flush=True)


if __name__ == "__main__":
    sys.exit(main())
