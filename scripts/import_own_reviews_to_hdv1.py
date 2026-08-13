#!/usr/bin/env python3
"""Import own-brand (Sonkuki) reviews from homedepot_reviews into
HDV1_Customer_Reviews with a boolean is_own flag.

- Adds column `is_own` (Checkbox) to HDV1_Customer_Reviews if missing.
- Existing competitor rows get is_own=false.
- homedepot_reviews rows are inserted with is_own=true (synthetic unique
  review_key since homedepot_reviews has no external review id).
"""

import hashlib
import json
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
HD_REV_TABLE = "mhejqhev6vgfkhz"    # homedepot_reviews
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def request(method, path, payload=None, retries=6, timeout=180):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, data=body, headers=headers, method=method), timeout=timeout)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"NocoDB request failed: {method} {path}: {exc}") from exc
            time.sleep(min(30, 2 ** attempt))


def table_columns(table_id):
    meta = request("GET", f"/api/v2/meta/tables/{table_id}")
    return {c["title"]: c for c in meta.get("columns", [])}


def all_records(table_id, fields):
    rows, offset = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": offset, "fields": fields})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def insert_batches(table_id, rows, batch_size=20):
    for start in range(0, len(rows), batch_size):
        request("POST", f"/api/v2/tables/{table_id}/records", rows[start:start + batch_size])
        print(f"  inserted {min(start + batch_size, len(rows))}/{len(rows)}", flush=True)


def update_flag(table_id, rows, flag):
    for start in range(0, len(rows), 20):
        batch = [{"Id": r["Id"], "is_own": flag} for r in rows[start:start + 20]]
        request("PATCH", f"/api/v2/tables/{table_id}/records", batch)
    print(f"  flagged {flag}: {len(rows)} rows", flush=True)


def main():
    cols = table_columns(CR_TABLE)
    if "is_own" not in cols:
        request("POST", f"/api/v2/meta/tables/{CR_TABLE}/columns",
                {"title": "is_own", "uidt": "Checkbox"})
        print("column is_own created", flush=True)
    else:
        print("column is_own already exists", flush=True)

    # competitor rows -> is_own=false (only rows not already flagged true)
    existing = all_records(CR_TABLE, "Id,is_own,review_key")
    to_flag_false = [r for r in existing if str(r.get("is_own")) != "1"]
    print(f"existing rows: {len(existing)} | rows to flag false: {len(to_flag_false)}", flush=True)
    update_flag(CR_TABLE, to_flag_false, False)

    # repair: any own-key rows that were flipped false -> back to true
    own_existing = [r for r in existing if str(r.get("review_key", "")).startswith("HOME_DEPOT:OWN:")]
    if own_existing:
        update_flag(CR_TABLE, own_existing, True)
        print(f"own rows re-flagged true: {len(own_existing)}", flush=True)

    # own reviews from homedepot_reviews
    src = all_records(HD_REV_TABLE,
                      "itemId,title,reviewText,rating,submissionTime,userNickname,authorId")
    print(f"own review source rows: {len(src)}", flush=True)

    # idempotency: skip review_keys already present in the target table
    existing_keys = {r.get("review_key") for r in all_records(CR_TABLE, "review_key") if r.get("review_key")}

    new_rows = []
    for r in src:
        rating = r.get("rating")
        try:
            rating = float(str(rating)) if rating not in (None, "") else None
        except (TypeError, ValueError):
            rating = None
        key_src = "|".join(str(r.get(k, "")) for k in ("itemId", "submissionTime", "authorId", "title"))
        key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:20]
        review_key = f"HOME_DEPOT:OWN:{key}"
        if review_key in existing_keys:
            continue
        new_rows.append({
            "review_key": review_key,
            "external_review_id": key,
            "review_date_iso_utc": r.get("submissionTime"),
            "rating": rating,
            "review_title": r.get("title"),
            "review_text": r.get("reviewText"),
            "reviewer_display_name": r.get("userNickname"),
            "is_own": True,
        })
    print(f"new own rows to insert: {len(new_rows)} (skipped {len(src) - len(new_rows)} existing)", flush=True)
    insert_batches(CR_TABLE, new_rows)

    final_rows = len(existing) + len(new_rows)
    print(f"done: HDV1_Customer_Reviews now {final_rows} rows "
          f"(competitor={len(existing)}, own={len(new_rows)})", flush=True)


if __name__ == "__main__":
    sys.exit(main())
