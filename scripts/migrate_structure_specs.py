#!/usr/bin/env python3
"""Backfill product_variants structure fields from flat listing source tables.

Copies width_ft, depth_ft, color from homedepot_products / competitor_products
specification columns when variant fields are empty.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from nocodb_client import TABLES, NocoClient, backup_jsonl

HD_PRODUCTS = "mnttfzrhu6gp6s0"
COMP_PRODUCTS = "m0vk08vypm4jrl7"

SPEC_WIDTH = "specifications|Approximate Width (ft.)"
SPEC_DEPTH = "specifications|Approximate Depth (ft.)"
SPEC_COLOR = "specifications|Color Family"


def norm(value) -> str:
    return str(value or "").strip()


def numeric(value) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def item_id_from_listing_key(listing_key: str) -> str | None:
    key = norm(listing_key)
    if key.startswith("HOME_DEPOT:"):
        return key.split(":", 1)[1]
    m = re.search(r"/(\d{6,})/?$", key.rstrip("/"))
    return m.group(1) if m else None


def build_spec_index(client: NocoClient) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for table_id in (HD_PRODUCTS, COMP_PRODUCTS):
        fields = ["Id", "url", "mpn", SPEC_WIDTH, SPEC_DEPTH, SPEC_COLOR]
        try:
            rows = client.records(table_id, fields)
        except RuntimeError:
            # table may lack some spec columns
            rows = client.records(table_id, ["Id", "url", "mpn"])
        for row in rows:
            item = None
            url = norm(row.get("url"))
            m = re.search(r"/(\d{6,})", url)
            if m:
                item = m.group(1)
            if not item:
                continue
            index[item] = {
                "width_ft": numeric(row.get(SPEC_WIDTH)),
                "depth_ft": numeric(row.get(SPEC_DEPTH)),
                "color": norm(row.get(SPEC_COLOR)) or None,
            }
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = args.apply

    client = NocoClient()
    spec_index = build_spec_index(client)
    variants = client.records(TABLES["variants"], ["Id", "variant_key", "width_ft", "depth_ft", "color"])
    listings = client.records(TABLES["listings"], ["listing_key", "variant_key"])

    vk_to_item: dict[str, str] = {}
    for listing in listings:
        vk = norm(listing.get("variant_key"))
        item = item_id_from_listing_key(norm(listing.get("listing_key")))
        if vk and item and vk not in vk_to_item:
            vk_to_item[vk] = item

    patches = []
    for variant in variants:
        vk = norm(variant.get("variant_key"))
        item = vk_to_item.get(vk)
        if not item or item not in spec_index:
            continue
        source = spec_index[item]
        patch = {"Id": variant["Id"]}
        changed = False
        for field in ("width_ft", "depth_ft", "color"):
            if variant.get(field) in (None, "", 0) and source.get(field) not in (None, ""):
                patch[field] = source[field]
                changed = True
        if changed:
            patches.append(patch)

    report = {
        "spec_sources_indexed": len(spec_index),
        "variants": len(variants),
        "rows_to_patch": len(patches),
        "sample": patches[:5],
    }
    if patches:
        report["backup"] = str(backup_jsonl(patches, "product_variants_structure_specs"))
    if apply and patches:
        report["patched"] = client.patch_records(TABLES["variants"], patches)

    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
