#!/usr/bin/env python3
"""Task 5: unify numeric column types (SingleLineText -> Number/Decimal).

Phase 1 (cleanup): strip thousands commas, currency symbols, k-suffix; fix
Excel-serial month values to ISO dates. Only touches the affected columns.
Phase 2 (convert): PATCH column uidt to Number/Decimal for clean numeric cols.
Phase 3 (verify): sample values after conversion.
"""

import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TABLES = {
    "competitor_product": "m0vk08vypm4jrl7",
    "homedepot_product": "mnttfzrhu6gp6s0",
    "competitor_product_sale": "munzznlmfzd9d2t",
    "gsc_page_all-time": "m0fl1tcxyopz1s3",
    "gsc_keyword_month": "m0e006r2m3d1wg5",
    "gsc_keyword_improved": "m1eh0kd0ryxeptu",
    "gsc_keyword_newly_ranked": "mj3l8mejz31n8ry",
}

# column -> target uidt (Decimal for values with possible decimals, else Number)
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

MONTH_SERIAL_TABLES = {"gsc_keyword_month", "gsc_keyword_improved", "gsc_keyword_newly_ranked"}


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


def all_records(table_id, fields=None):
    rows, offset = [], 0
    while True:
        p = {"limit": 1000, "offset": offset}
        if fields:
            p["fields"] = ",".join(fields)
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{urlencode(p)}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def meta_columns(table_id):
    return request("GET", f"/api/v2/meta/tables/{table_id}").get("columns", [])


def clean_number(v):
    """'$3,899' -> 3899 ; '507.2k' -> 507200 ; '1,925' -> 1925 ; else None"""
    s = str(v).strip()
    if not s:
        return None
    s = s.replace(",", "").replace("$", "").strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)([kKmM]?)$", s)
    if not m:
        return None
    num = float(m.group(1))
    suffix = m.group(2).lower()
    if suffix == "k":
        num *= 1000
    elif suffix == "m":
        num *= 1000000
    return num


def phase_cleanup():
    # gsc_page_all-time: strip thousands separators in Rows/Impressions
    tid = TABLES["gsc_page_all-time"]
    rows = all_records(tid, ["Id", "Rows", "Impressions"])
    patches = []
    for r in rows:
        up = {}
        for col in ("Rows", "Impressions"):
            v = r.get(col)
            if v and "," in str(v):
                cleaned = str(v).replace(",", "")
                if cleaned != str(v):
                    up[col] = cleaned
        if up:
            patches.append({"Id": r["Id"], **up})
    for start in range(0, len(patches), 50):
        request("PATCH", f"/api/v2/tables/{tid}/records", patches[start:start + 50])
    print(f"cleanup gsc_page_all-time commas: {len(patches)} rows", flush=True)

    # competitor_product_sale: normalize 售价 / 估算销量
    tid = TABLES["competitor_product_sale"]
    rows = all_records(tid, ["Id", "售价", "估算销量"])
    patches = []
    for r in rows:
        up = {}
        for col in ("售价", "估算销量"):
            v = r.get(col)
            if not v:
                continue
            c = clean_number(v)
            if c is not None and str(c) != str(v).replace(",", "").replace("$", ""):
                up[col] = c
        if up:
            patches.append({"Id": r["Id"], **up})
    for start in range(0, len(patches), 50):
        request("PATCH", f"/api/v2/tables/{tid}/records", patches[start:start + 50])
    print(f"cleanup competitor_product_sale currency/k: {len(patches)} rows", flush=True)

    # month serial -> ISO in three month tables
    for title in MONTH_SERIAL_TABLES:
        tid = TABLES[title]
        rows = all_records(tid, ["Id", "month"])
        patches = []
        for r in rows:
            v = str(r.get("month") or "").strip()
            if ISO_RE.match(v):
                continue
            try:
                days = float(v)
                iso = (datetime(1899, 12, 30) + timedelta(days=days)).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                continue
            patches.append({"Id": r["Id"], "month": iso})
        for start in range(0, len(patches), 50):
            request("PATCH", f"/api/v2/tables/{tid}/records", patches[start:start + 50])
        print(f"cleanup {title} month serials: {len(patches)} rows", flush=True)


def phase_convert():
    for title, tid in TABLES.items():
        cols = {c["title"]: c for c in meta_columns(tid)}
        plan = CONVERT.get(title, {})
        for colname, target in plan.items():
            col = cols.get(colname)
            if not col:
                print(f"  {title}.{colname}: column missing, skip", flush=True)
                continue
            if col["uidt"] == target:
                print(f"  {title}.{colname}: already {target}", flush=True)
                continue
            try:
                request("PATCH", f"/api/v2/meta/columns/{col['id']}", {"uidt": target})
                print(f"  {title}.{colname}: {col['uidt']} -> {target}", flush=True)
            except Exception as exc:
                print(f"  {title}.{colname}: CONVERT FAILED {exc}", flush=True)
            time.sleep(2)  # gentle pacing; fast meta PATCHes crashed the server before


def phase_verify():
    for title, tid in TABLES.items():
        cols = {c["title"]: c["uidt"] for c in meta_columns(tid)}
        plan = CONVERT.get(title, {})
        changed = [c for c in plan if cols.get(c) == plan[c]]
        print(f"{title}: converted OK: {len(changed)}/{len(plan)} -> {sorted(changed)}", flush=True)


if __name__ == "__main__":
    if os.environ.get("SKIP_CLEANUP") != "1":
        phase_cleanup()
    phase_convert()
    phase_verify()
