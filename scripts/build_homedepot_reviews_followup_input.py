#!/usr/bin/env python3
"""Build one-input-per-page follow-up requests for the reviews Actor."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def build_followup_requests(first_page_output: Path, max_pages: int) -> list[dict]:
    records = json.loads(first_page_output.read_text(encoding="utf-8"))
    by_item: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        item_id = record.get("itemId")
        if item_id:
            by_item[item_id].append(record)

    requests: list[dict] = []
    for item_id in sorted(by_item):
        item_records = by_item[item_id]
        if not any(record.get("statusMessage") == "FOUND" for record in item_records):
            continue
        last_page = max((record.get("lastPage") or 1) for record in item_records)
        for page in range(2, min(last_page, max_pages) + 1):
            requests.append(
                {
                    "itemId": item_id,
                    "startPage": page,
                    "endPage": page,
                    "sortBy": "photoreview",
                }
            )
    return requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("first_page_output", type=Path)
    parser.add_argument("input_output", type=Path)
    parser.add_argument("manifest_output", type=Path)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()

    requests = build_followup_requests(args.first_page_output, args.max_pages)
    payload = {"input": requests}
    args.input_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.manifest_output.write_text(
        json.dumps(
            {
                "sourceFirstPageOutput": str(args.first_page_output),
                "actor": "axesso_data/homedepot-reviews-scraper",
                "maxPagesPerProduct": args.max_pages,
                "requestCount": len(requests),
                "requests": requests,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"followup_requests={len(requests)}")
    print(f"input={args.input_output}")
    print(f"manifest={args.manifest_output}")


if __name__ == "__main__":
    main()
