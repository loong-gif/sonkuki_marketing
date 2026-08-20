#!/usr/bin/env python3
# DEPRECATED: References deleted ingest tables (removed 2026-08):
# homedepot_products, competitor_products, competitor_sales, raw_listing_snapshots.
# Do not run — kept for historical reference.
"""Scan SingleLineText columns for numeric content (read-only)."""
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
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")

TARGETS = {
    "competitor_product": "m0vk08vypm4jrl7",
    "homedepot_product": "mnttfzrhu6gp6s0",
    "competitor_product_sale": "munzznlmfzd9d2t",
    "gsc_page_all-time": "m0fl1tcxyopz1s3",
    "gsc_keyword_all-time": "muav8zitnoqlauu",
    "gsc_keyword_month": "m0e006r2m3d1wg5",
    "gsc_keyword_improved": "m1eh0kd0ryxeptu",
    "gsc_keyword_newly_ranked": "mj3l8mejz31n8ry",
}


def request(method, path, retries=8, timeout=90):
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, headers={"xc-token": TOKEN, "accept": "application/json"}, method=method), timeout=timeout)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, ConnectionResetError, socket.timeout, OSError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"failed {path}: {exc}") from exc
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
    for title, tid in sorted(TARGETS.items()):
        meta = request("GET", f"/api/v2/meta/tables/{tid}")
        text_cols = [c for c in meta.get("columns", []) if c["uidt"] == "SingleLineText"]
        if not text_cols:
            print(f"{title}: no text cols", flush=True)
            continue
        rows = all_records(tid)
        print(f"\n{title} ({len(rows)} rows)", flush=True)
        for c in text_cols:
            name = c["title"]
            vals = [str(r.get(name) or "").strip() for r in rows]
            nonempty = [v for v in vals if v]
            if not nonempty:
                continue
            numeric = sum(1 for v in nonempty if NUM_RE.match(v))
            pct = numeric * 100 // len(nonempty)
            sample = nonempty[0][:30] if nonempty else ""
            print(f"  {name:40s} nonempty={len(nonempty):>5d} numeric={numeric:>5d} ({pct:>3d}%) sample={sample!r}", flush=True)
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
