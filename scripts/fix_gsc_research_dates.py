#!/usr/bin/env python3
"""Fix gsc_keyword_research.date: Excel serial number -> ISO date.

Only the `date` field is touched (per user rule: never modify adjacent columns).
"""

import json
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
TABLE = "m2go76sjanzvx7s"        # gsc_keyword_research
RAW_TABLE = "mfbg6s0mv9l74ky"    # gsc_data_raw (for date-range validation)
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def serial_to_iso(v):
    try:
        days = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    if days < 20000 or days > 80000:  # out of plausible Excel date range
        return None
    return (datetime(1899, 12, 30) + timedelta(days=days)).strftime("%Y-%m-%d")


def main():
    rows = all_records(TABLE, ["Id", "date"])
    print(f"loaded {len(rows)} rows", flush=True)

    fixes = []
    skipped = 0
    for r in rows:
        d = str(r.get("date") or "").strip()
        if ISO_RE.match(d):
            continue
        iso = serial_to_iso(d)
        if iso is None:
            skipped += 1
            print(f"  SKIP Id={r['Id']} date={d!r} (not convertible)", flush=True)
            continue
        fixes.append({"Id": r["Id"], "date": iso})
    print(f"to fix: {len(fixes)} | skipped: {skipped}", flush=True)

    if not fixes:
        print("nothing to fix", flush=True)
        return

    for start in range(0, len(fixes), 50):
        request("PATCH", f"/api/v2/tables/{TABLE}/records", fixes[start:start + 50])
        print(f"  patched {min(start + 50, len(fixes))}/{len(fixes)}", flush=True)

    # validate
    after = all_records(TABLE, ["Id", "date"])
    bad = [r for r in after if not ISO_RE.match(str(r.get("date") or "").strip())]
    dates = sorted(str(r["date"]) for r in after if r.get("date"))
    print(f"after: rows={len(after)}, non-ISO remaining={len(bad)}, "
          f"range={dates[0]} -> {dates[-1]}", flush=True)

    # compare with gsc_data_raw date range
    raw = all_records(RAW_TABLE, ["date"])
    raw_dates = sorted(str(r["date"]) for r in raw if r.get("date"))
    print(f"gsc_data_raw range: {raw_dates[0]} -> {raw_dates[-1]} ({len(raw_dates)} rows)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
