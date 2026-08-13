#!/usr/bin/env python3
"""Backfill Query_Summary.CTR from Clicks / Impressions."""

import json
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
TABLE_ID = "muav8zitnoqlauu"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(6):
        try:
            with OPENER.open(Request(API + path, data=body, method=method, headers=headers), timeout=90) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected) as exc:
            last = exc
            if attempt + 1 < 6:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB request failed: {method} {path}: {last}")


def list_rows():
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset, "fields": "Id,分组键,Clicks,Impressions,CTR"}
        batch = request("GET", f"/api/v2/tables/{TABLE_ID}/records?{urlencode(params)}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def main():
    rows = list_rows()
    if len(rows) != 2013:
        raise RuntimeError(f"Expected 2013 Query_Summary rows, got {len(rows)}")
    existing = [row for row in rows if row.get("CTR") not in (None, "")]
    if existing:
        raise RuntimeError(f"Refusing to overwrite {len(existing)} existing CTR values")
    updates = []
    for row in rows:
        clicks = float(row.get("Clicks") or 0)
        impressions = float(row.get("Impressions") or 0)
        ctr = clicks / impressions if impressions else 0.0
        updates.append({"Id": row["Id"], "CTR": ctr})
    for start in range(0, len(updates), 50):
        batch = updates[start : start + 50]
        request("PATCH", f"/api/v2/tables/{TABLE_ID}/records", batch)
        print(f"updated CTR {min(start + 50, len(updates))}/{len(updates)}", flush=True)

    final_rows = list_rows()
    mismatches = []
    for row in final_rows:
        clicks = float(row.get("Clicks") or 0)
        impressions = float(row.get("Impressions") or 0)
        expected = clicks / impressions if impressions else 0.0
        actual = row.get("CTR")
        if actual is None or abs(float(actual) - expected) > 1e-6:
            mismatches.append({"Id": row.get("Id"), "expected": expected, "actual": actual})
    if mismatches:
        raise RuntimeError(json.dumps({"ctr_mismatches": mismatches[:10], "count": len(mismatches)}, ensure_ascii=False))
    samples = [{"query": row.get("分组键"), "CTR": row.get("CTR")} for row in final_rows[:3]]
    print(json.dumps({"status": "passed", "rows": len(final_rows), "ctr_nonempty": sum(row.get("CTR") not in (None, "") for row in final_rows), "samples": samples}, ensure_ascii=False))


if __name__ == "__main__":
    main()
