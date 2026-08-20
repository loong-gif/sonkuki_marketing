#!/usr/bin/env python3
# DEPRECATED: Targets deleted NocoDB tables (removed 2026-08):
# homedepot_products (mnttfzrhu6gp6s0), competitor_products (m0vk08vypm4jrl7),
# competitor_sales (munzznlmfzd9d2t). Do not run — kept for historical reference.
"""Chunked column-type conversion with server health checks.

NocoDB on this Windows host restarts its worker after a few meta PATCHes and
is unreachable for ~2-3 minutes. This script converts columns one at a time,
sleeps between calls, and waits for the server to come back before continuing.
"""

import json
import os
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))

TABLES = {
    "competitor_product": "m0vk08vypm4jrl7",
    "homedepot_product": "mnttfzrhu6gp6s0",
    "competitor_product_sale": "munzznlmfzd9d2t",
    "gsc_page_all-time": "m0fl1tcxyopz1s3",
    "gsc_keyword_month": "m0e006r2m3d1wg5",
    "gsc_keyword_improved": "m1eh0kd0ryxeptu",
    "gsc_keyword_newly_ranked": "mj3l8mejz31n8ry",
}
CONVERT = {
    "competitor_product": {
        "salePrice": "Decimal", "originalPrice": "Decimal", "rating": "Decimal",
        "reviewCount": "Number", "inventory|quantity": "Number", "quantityLimit": "Number",
        "savings": "Number", "savingsPercent": "Decimal", "totalReviews": "Number",
        "totalVariants": "Number",
        "specifications|Approximate Depth (ft.)": "Decimal",
        "specifications|Approximate Height (ft.)": "Decimal",
        "specifications|Approximate Width (ft.)": "Decimal",
    },
    "homedepot_product": {
        "offers/price": "Decimal", "originalPrice": "Decimal", "totalVariants": "Number",
        "rating": "Decimal", "reviewCount": "Number",
    },
    "competitor_product_sale": {
        "售价": "Decimal", "估算销量": "Number", "评分": "Decimal",
        "评论总数": "Number", "近12月占比": "Decimal",
    },
    "gsc_page_all-time": {
        "Rows": "Number", "Clicks": "Number", "Impressions": "Number",
        "Weighted_Avg_Position": "Decimal", "Queries": "Number",
    },
    "gsc_keyword_month": {
        "clicks": "Number", "impression_tmp": "Number", "avg_position": "Decimal",
    },
    "gsc_keyword_improved": {
        "avg_position": "Number", "impressions": "Number", "clicks": "Number",
    },
    "gsc_keyword_newly_ranked": {
        "avg_position": "Number", "impressions": "Number", "clicks": "Number",
    },
}


def request(method, path, payload=None, timeout=60, retries=8):
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


def wait_server_up(max_minutes=12):
    deadline = time.time() + max_minutes * 60
    while time.time() < deadline:
        if server_up():
            return True
        time.sleep(20)
    return False


def col_state(tid):
    meta = request("GET", f"/api/v2/meta/tables/{tid}", timeout=60)
    return {c["title"]: (c["id"], c["uidt"]) for c in meta.get("columns", [])}


def main():
    todo = [(t, c, u) for t, plan in CONVERT.items() for c, u in plan.items()]
    print(f"plan: {len(todo)} columns", flush=True)
    if not wait_server_up():
        print("server never came up", flush=True)
        sys.exit(1)

    done = 0
    for title, colname, target in todo:
        # fresh column state each time (cheap, avoids stale ids)
        try:
            cols = col_state(TABLES[title])
        except Exception as exc:
            print(f"meta fetch failed ({title}): {exc} -> waiting", flush=True)
            if not wait_server_up():
                print("abort: server down too long", flush=True)
                sys.exit(1)
            cols = col_state(TABLES[title])
        if colname not in cols:
            print(f"  SKIP {title}.{colname}: column missing", flush=True)
            done += 1
            continue
        cid, cur = cols[colname]
        if cur == target:
            print(f"  {title}.{colname}: already {target}", flush=True)
            done += 1
            continue
        try:
            request("PATCH", f"/api/v2/meta/columns/{cid}", {"uidt": target}, timeout=90)
            print(f"  {title}.{colname}: {cur} -> {target}", flush=True)
            done += 1
        except Exception as exc:
            print(f"  {title}.{colname}: FAILED {exc}", flush=True)
        time.sleep(15)  # gentle pacing; meta PATCHes crash the worker if too fast
        if not server_up():
            print("  server went down -> waiting for recovery", flush=True)
            if not wait_server_up():
                print("abort: server down too long", flush=True)
                sys.exit(1)

    # final verification
    ok, fail = [], []
    for title, colname, target in CONVERT.items():
        for c, u in col_state(TABLES[title]).items():
            pass
        cols = col_state(TABLES[title])
        for colname, target in CONVERT[title].items():
            (ok if cols.get(colname, ("", None))[1] == target else fail).append(f"{title}.{colname}")
    print(f"\nverify: ok={len(ok)} fail={len(fail)}", flush=True)
    if fail:
        print("failed:", fail, flush=True)


if __name__ == "__main__":
    main()
