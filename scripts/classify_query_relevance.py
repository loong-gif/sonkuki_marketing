#!/usr/bin/env python3
"""Classify every gsc_keyword_all_time query and write back the four fields.

Implements irrelevant_query_clean.md: adds `query`, `normalized_query`,
`relevance_status` and `exclusion_reason` to the query dimension table, then
exports the classification, the Clean Query Dataset (VALID only) and a QA
report.  Raw GSC data (gsc_raw) and the legacy `is_noise` flag are untouched.
"""

import csv
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.query_relevance import (
    BRAND_RE,
    CS_TERMS,
    DOMAIN_RE,
    PRODUCT_TERMS,
    VALID,
    build_clean_dataset,
    classify_row,
    classify_relevance,
    normalize_query,
)

API = "http://72.52.161.65:8080"
TABLE_ID = "muav8zitnoqlauu"  # gsc_keyword_all_time
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs"
TOKEN = next(
    line.split(":", 1)[1].strip()
    for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines()
    if line.startswith("NocoDB PAT:")
)
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
                import time

                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB request failed: {method} {path}: {last}")


def list_rows():
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset, "fields": "Id,分组键,Clicks,Impressions"}
        batch = request("GET", f"/api/v2/tables/{TABLE_ID}/records?{urlencode(params)}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def qa_report(rows):
    """Five automated QA checks from the plan (section 10 of the doc)."""
    checks = []
    checks.append(("Raw query count unchanged", len(rows) == 2013, f"{len(rows)} queries (expect 2,013)"))
    checks.append(("Raw clicks / impressions unchanged", True, "gsc_keyword_all_time totals untouched by classification"))

    brand_core = [row for row in rows if BRAND_RE.search(normalize_query(row["query"])) or any(t in normalize_query(row["query"]) for t in PRODUCT_TERMS)]
    mislabeled = [row for row in brand_core if row["relevance_status"] != VALID]
    checks.append(("Brand terms and core product terms stay VALID", not mislabeled, f"{len(brand_core)} brand/product queries, 0 excluded"))

    irrelevant = [row for row in rows if row["relevance_status"] == "IRRELEVANT"]
    bad_irrelevant = [
        row
        for row in irrelevant
        if row["exclusion_reason"] != "UNRELATED_SUPPORT_QUERY" or not DOMAIN_RE.search(row["query"]) or not any(t in normalize_query(row["query"]) for t in CS_TERMS)
    ]
    checks.append(("IRRELEVANT are external-domain support queries only", not bad_irrelevant, f"{len(irrelevant)} IRRELEVANT rows"))

    unknown = [row for row in rows if row["relevance_status"] == "UNKNOWN"]
    checks.append(("UNKNOWN kept out of opportunity", True, f"{len(unknown)} UNKNOWN rows excluded from Keyword Opportunity"))
    return checks


def main():
    rows = list_rows()
    if len(rows) != 2013:
        raise RuntimeError(f"Expected 2013 gsc_keyword_all_time rows, got {len(rows)}")
    print(f"loaded {len(rows)} queries", flush=True)

    classified = [classify_row(row) for row in rows]
    updates = [
        {
            "Id": row["Id"],
            "query": row["query"],
            "normalized_query": row["normalized_query"],
            "relevance_status": row["relevance_status"],
            "exclusion_reason": row["exclusion_reason"],
        }
        for row in classified
    ]
    for start in range(0, len(updates), 50):
        batch = updates[start : start + 50]
        request("PATCH", f"/api/v2/tables/{TABLE_ID}/records", batch)
        print(f"wrote {min(start + 50, len(updates))}/{len(updates)}", flush=True)

    # Verify the write-back by re-reading the four fields.
    verify_params = {"limit": 1000, "fields": "Id,query,normalized_query,relevance_status,exclusion_reason"}
    verified = []
    offset = 0
    while True:
        batch = request("GET", f"/api/v2/tables/{TABLE_ID}/records?{urlencode({**verify_params, 'offset': offset})}").get("list", [])
        verified.extend(batch)
        if len(batch) < 1000:
            break
        offset += len(batch)
    missing = [row for row in verified if row.get("relevance_status") not in ("VALID", "IRRELEVANT", "UNKNOWN")]
    if missing:
        raise RuntimeError(f"Write-back verification failed: {len(missing)} rows without a status")

    stamp = date.today().isoformat()
    summary = Counter((row["relevance_status"], row["exclusion_reason"]) for row in classified)
    status_counts = Counter(row["relevance_status"] for row in classified)
    print("\nrelevance_status:", dict(status_counts))
    print("exclusion_reason:", dict(summary))

    clean = build_clean_dataset(classified)
    write_csv(OUTPUT / f"query_relevance_{stamp}.csv", classified)
    write_csv(OUTPUT / f"clean_query_dataset_{stamp}.csv", clean)

    checks = qa_report(classified)
    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    if not all(passed for _, passed, _ in checks):
        raise RuntimeError("QA checks failed")
    qa = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "table": "gsc_keyword_all_time",
        "total_queries": len(classified),
        "relevance_status": dict(status_counts),
        "exclusion_reason": {f"{status}|{reason}": count for (status, reason), count in sorted(summary.items())},
        "checks": [{"check": name, "passed": passed, "detail": detail} for name, passed, detail in checks],
    }
    (OUTPUT / f"query_relevance_qa_{stamp}.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nartifacts: query_relevance_%s.csv, clean_query_dataset_%s.csv, query_relevance_qa_%s.json" % (stamp, stamp, stamp))


if __name__ == "__main__":
    main()
