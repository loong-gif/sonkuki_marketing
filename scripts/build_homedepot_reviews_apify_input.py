#!/usr/bin/env python3
"""Build validated input for the Home Depot reviews Apify Actor."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ITEM_ID_PATTERN = re.compile(r"\d+")


def extract_item_id(url: str) -> str:
    """Extract the numeric Home Depot item ID from a product URL."""
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        raise ValueError(f"URL has no path: {url}")
    item_id = path_parts[-1]
    if not ITEM_ID_PATTERN.fullmatch(item_id):
        raise ValueError(f"URL does not end in a numeric item ID: {url}")
    return item_id


def build_input(csv_path: Path, max_pages: int) -> tuple[dict, list[dict]]:
    """Return Actor input and a source manifest keyed by item ID."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    if not rows:
        raise ValueError(f"CSV is empty: {csv_path}")
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")

    actor_items: list[dict] = []
    manifest: list[dict] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        url = (row.get("url") or "").strip()
        if not url:
            raise ValueError(f"Missing url at CSV row {row_number}")
        item_id = extract_item_id(url)
        if item_id in seen_ids:
            raise ValueError(f"Duplicate item ID {item_id} at CSV row {row_number}")
        seen_ids.add(item_id)
        actor_items.append(
            {
                "itemId": item_id,
                "startPage": 1,
                "endPage": max_pages,
                "sortBy": "photoreview",
            }
        )
        manifest.append(
            {
                "rowNumber": row_number,
                "itemId": item_id,
                "mpn": row.get("mpn"),
                "name": row.get("name"),
                "reviewCountExpected": row.get("reviewCount"),
                "url": url,
            }
        )

    return {"input": actor_items}, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("input_output", type=Path)
    parser.add_argument("manifest_output", type=Path)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()

    actor_input, manifest = build_input(args.csv_path, args.max_pages)
    args.input_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.input_output.write_text(
        json.dumps(actor_input, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.manifest_output.write_text(
        json.dumps(
            {
                "sourceCsv": str(args.csv_path),
                "actor": "axesso_data/homedepot-reviews-scraper",
                "maxPagesPerProduct": args.max_pages,
                "productCount": len(manifest),
                "products": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"products={len(manifest)}")
    print(f"input={args.input_output}")
    print(f"manifest={args.manifest_output}")


if __name__ == "__main__":
    main()
