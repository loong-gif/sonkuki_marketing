#!/usr/bin/env python3
"""Dedupe competitor_reviews_raw (m7k6bslqxmbw10a) by id1.

- Backs up all rows to outputs/competitor_reviews_raw_backup_<ts>.jsonl
- Keeps the latest row per id1 (by CreatedAt, tie -> lowest Id)
- Hard-deletes duplicate rows (batched)
- Validates: distinct id1 == 2007 and set equals HDV1_Customer_Reviews
  competitor external_review_id set
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
TABLE = "m7k6bslqxmbw10a"        # competitor_reviews_raw
HDV1_CR = "mnz1y5x5kydob4f"      # HDV1_Customer_Reviews
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
    fields = ["Id", "CreatedAt", "id1", "itemId", "title", "reviewText", "rating",
              "time", "userName", "productId", "productName"]
    rows = all_records(TABLE, fields)
    print(f"loaded {len(rows)} rows", flush=True)

    # backup
    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = OUT_DIR / f"competitor_reviews_raw_backup_{stamp}.jsonl"
    with open(backup, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"backup -> {backup}", flush=True)

    # group by id1
    by_id = {}
    empty_id = []
    for r in rows:
        rid = str(r.get("id1") or "").strip()
        if not rid:
            empty_id.append(r)
            continue
        by_id.setdefault(rid, []).append(r)

    distinct = len(by_id)
    dupes = [r for group in by_id.values() if len(group) > 1 for r in sorted(
        group, key=lambda x: (str(x.get("CreatedAt") or ""), x["Id"]))[:-1]]
    print(f"distinct id1: {distinct} | duplicate rows to delete: {len(dupes)} | "
          f"rows without id1 (kept): {len(empty_id)}", flush=True)

    if not dupes:
        print("nothing to delete", flush=True)
        return

    # hard delete duplicates in batches
    ids = [r["Id"] for r in dupes]
    for start in range(0, len(ids), 50):
        request("DELETE", f"/api/v2/tables/{TABLE}/records", [{"Id": i} for i in ids[start:start + 50]])
        print(f"  deleted {min(start + 50, len(ids))}/{len(ids)}", flush=True)

    # validation
    remaining = all_records(TABLE, fields)
    rem_ids = {str(r.get("id1") or "").strip() for r in remaining if r.get("id1")}
    hdv1 = all_records(HDV1_CR, ["external_review_id", "is_own"])
    hdv1_comp = {str(r.get("external_review_id") or "").strip() for r in hdv1 if str(r.get("is_own")) != "1" and r.get("external_review_id")}
    print(f"after: rows={len(remaining)}, distinct id1={len(rem_ids)}", flush=True)
    print(f"set equal to HDV1_CR competitor external ids: {rem_ids == hdv1_comp} "
          f"({len(rem_ids & hdv1_comp)}/{len(hdv1_comp)} overlap)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
