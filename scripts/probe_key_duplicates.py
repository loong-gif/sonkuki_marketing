#!/usr/bin/env python3
"""Read-only probe for duplicate business keys across HDV1 tables."""

from __future__ import annotations

import json
import sys

from nocodb_client import TABLES, NocoClient, duplicate_record_ids

KEY_COLUMNS = [
    ("brands", "brand_key"),
    ("products", "product_key"),
    ("variants", "variant_key"),
    ("listings", "listing_key"),
    ("reviews", "review_key"),
    ("links", "link_key"),
]


def main() -> int:
    client = NocoClient()
    report = []
    for table_key, column in KEY_COLUMNS:
        rows = client.records(TABLES[table_key], ["Id", column])
        kept, dup_ids = duplicate_record_ids(rows, column)
        report.append(
            {
                "table": table_key,
                "column": column,
                "rows": len(rows),
                "distinct_keys": len(kept),
                "duplicate_rows": len(dup_ids),
                "duplicate_ids": dup_ids[:10],
            }
        )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
