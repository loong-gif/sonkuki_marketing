#!/usr/bin/env python3
"""Migrate gsc_keyword_research analysis columns into gsc_data_raw, then
archive + delete research (Task 3 / F3, option A).

Analysis columns moved: branded_type, total_clicks_all_pages,
total_impressions_all_pages, positions_tmp_all_pages.
Join key: (date, page_url, query_text).
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
RESEARCH = "m2go76sjanzvx7s"    # gsc_keyword_research
RAW = "mfbg6s0mv9l74ky"         # gsc_data_raw
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))
NEW_COLS = ["branded_type", "total_clicks_all_pages", "total_impressions_all_pages",
            "positions_tmp_all_pages"]


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
        q = urlencode(p)
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{q}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def table_columns(table_id):
    meta = request("GET", f"/api/v2/meta/tables/{table_id}")
    return {c["title"] for c in meta.get("columns", [])}


def main():
    # 1. ensure columns exist on raw
    cols = table_columns(RAW)
    for c in NEW_COLS:
        if c not in cols:
            request("POST", f"/api/v2/meta/tables/{RAW}/columns", {"title": c, "uidt": "SingleLineText"})
            print(f"column created: {c}", flush=True)
        else:
            print(f"column exists: {c}", flush=True)

    # 2. load research rows
    res = all_records(RESEARCH)
    print(f"research rows: {len(res)}", flush=True)

    # 3. load raw rows with expanded links
    raw_rows = all_records(RAW)
    raw_by_key = {}
    dup_keys = set()
    for r in raw_rows:
        page = r.get("page") or {}
        query = r.get("query") or {}
        key = "|".join([
            str(r.get("date") or "").strip(),
            str(page.get("page_url") or "").strip() if isinstance(page, dict) else str(page).strip(),
            str(query.get("分组键") or "").strip() if isinstance(query, dict) else str(query).strip(),
        ])
        if key in raw_by_key:
            dup_keys.add(key)
        else:
            raw_by_key[key] = r
    print(f"raw rows: {len(raw_rows)}, unique join keys: {len(raw_by_key)}, ambiguous keys: {len(dup_keys)}", flush=True)

    # 4. build patches
    patches = []
    unmatched = []
    for r in res:
        key = "|".join([
            str(r.get("date") or "").strip(),
            str(r.get("page") or "").strip(),
            str(r.get("query") or "").strip(),
        ])
        if key in dup_keys or key not in raw_by_key:
            unmatched.append(key)
            continue
        patches.append({
            "Id": raw_by_key[key]["Id"],
            **{c: r.get(c) for c in NEW_COLS},
        })
    print(f"patches: {len(patches)} | unmatched: {len(unmatched)}", flush=True)
    for u in unmatched[:10]:
        print("  unmatched key:", u[:120], flush=True)

    if len(unmatched) > 0:
        print("ABORT: not all rows matched; refusing to continue (no delete)", flush=True)
        return

    # 5. apply patches (only the 4 analysis columns)
    for start in range(0, len(patches), 50):
        request("PATCH", f"/api/v2/tables/{RAW}/records", patches[start:start + 50])
        print(f"  patched {min(start + 50, len(patches))}/{len(patches)}", flush=True)

    # 6. validate backfill
    check = all_records(RAW, ["Id"] + NEW_COLS)
    filled = {c: sum(1 for r in check if r.get(c) not in (None, "")) for c in NEW_COLS}
    print(f"validation filled counts: {filled} / {len(check)}", flush=True)
    if any(filled[c] != len(res) for c in NEW_COLS):
        print("ABORT: backfill incomplete; research table NOT deleted", flush=True)
        return

    # 7. backup research then delete
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = OUT_DIR / f"gsc_keyword_research_archived_{stamp}.jsonl"
    with open(backup, "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"research backup -> {backup}", flush=True)
    request("DELETE", f"/api/v2/meta/tables/{RESEARCH}")
    print("research table deleted", flush=True)

    # 8. confirm gone
    remaining = table_columns(RAW)
    print(f"raw columns now: {len(remaining)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
