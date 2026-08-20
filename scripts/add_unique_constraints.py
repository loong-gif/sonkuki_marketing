#!/usr/bin/env python3
"""Add unique constraints to business-key columns (Phase 4).

PATCH /api/v2/meta/columns/{columnId} {"unique": true} — one column at a time,
health check + >=15s pause between column changes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.client import RemoteDisconnected

from nocodb_client import TABLES, NocoClient, duplicate_record_ids

UNIQUE_COLUMNS = [
    ("brands", "brand_key"),
    ("products", "product_key"),
    ("variants", "variant_key"),
    ("listings", "listing_key"),
    ("reviews", "review_key"),
    ("links", "link_key"),
]

PACE_SECONDS = 15


def probe_duplicates(client: NocoClient, table_key: str, column: str) -> int:
    table_id = TABLES[table_key]
    rows = client.records(table_id, ["Id", column])
    _, dup_ids = duplicate_record_ids(rows, column)
    return len(dup_ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Probe only; do not PATCH")
    parser.add_argument("--apply", action="store_true", help="Apply unique constraints")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    client = NocoClient()
    results = []

    for table_key, column in UNIQUE_COLUMNS:
        dup_count = probe_duplicates(client, table_key, column)
        col = client.column_by_title(TABLES[table_key], column)
        entry = {
            "table": table_key,
            "column": column,
            "duplicate_rows": dup_count,
            "column_id": col.get("id") if col else None,
            "already_unique": bool(col and col.get("unique")),
        }
        if dup_count:
            entry["status"] = "blocked_duplicates"
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            if args.apply:
                print("STOP: duplicates remain; refusing to add unique constraints", flush=True)
                break
            continue

        if args.dry_run or entry["already_unique"]:
            entry["status"] = "dry_run_ok" if args.dry_run else "already_unique"
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            continue

        # apply unique
        try:
            client.health()
            client.request(
                "PATCH",
                f"/api/v2/meta/columns/{col['id']}",
                {"unique": True},
                retries=2,
                timeout=60,
            )
            entry["status"] = "unique_added"
        except (RuntimeError, RemoteDisconnected) as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            print("STOP: meta API error", flush=True)
            break

        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        time.sleep(PACE_SECONDS)

    summary = {"results": results}
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
