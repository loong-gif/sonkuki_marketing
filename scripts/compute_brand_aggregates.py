#!/usr/bin/env python3
"""Recompute denormalized aggregate columns on brands from the product chain."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

from nocodb_client import TABLES, NocoClient, backup_jsonl


def norm(value) -> str:
    return str(value or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = args.apply

    client = NocoClient()
    meta = client.table_meta(TABLES["brands"])
    col_titles = {c["title"] for c in meta.get("columns", [])}
    aggregate_fields = [f for f in ("product_count", "variant_count", "listing_count") if f in col_titles]
    if not aggregate_fields:
        print(json.dumps({"warning": "no aggregate columns on brands; nothing to update"}))
        return 0

    products = client.records(TABLES["products"], ["product_key", "brand_key"])
    variants = client.records(TABLES["variants"], ["variant_key", "product_key"])
    listings = client.records(TABLES["listings"], ["listing_key", "variant_key"])
    brands = client.records(TABLES["brands"], ["Id", "brand_key", *aggregate_fields])

    pk_to_brand = {norm(p["product_key"]): norm(p["brand_key"]) for p in products if norm(p.get("product_key"))}
    vk_to_pk = {norm(v["variant_key"]): norm(v["product_key"]) for v in variants if norm(v.get("variant_key"))}

    product_counts: Counter[str] = Counter()
    variant_counts: Counter[str] = Counter()
    listing_counts: Counter[str] = Counter()

    for product in products:
        bk = norm(product.get("brand_key"))
        if bk:
            product_counts[bk] += 1
    for variant in variants:
        pk = norm(variant.get("product_key"))
        bk = pk_to_brand.get(pk, "")
        if bk:
            variant_counts[bk] += 1
    for listing in listings:
        vk = norm(listing.get("variant_key"))
        pk = vk_to_pk.get(vk, "")
        bk = pk_to_brand.get(pk, "")
        if bk:
            listing_counts[bk] += 1

    patches = []
    for brand in brands:
        bk = norm(brand.get("brand_key"))
        desired = {
            "product_count": product_counts.get(bk, 0),
            "variant_count": variant_counts.get(bk, 0),
            "listing_count": listing_counts.get(bk, 0),
        }
        patch = {"Id": brand["Id"]}
        changed = False
        for field in aggregate_fields:
            if brand.get(field) != desired[field]:
                patch[field] = desired[field]
                changed = True
        if changed:
            patches.append(patch)

    report = {
        "aggregate_fields": aggregate_fields,
        "brands": len(brands),
        "rows_to_patch": len(patches),
        "sample": patches[:3],
    }
    if patches:
        report["backup"] = str(backup_jsonl(patches, "brands_aggregates_patch"))
    if apply and patches:
        report["patched"] = client.patch_records(TABLES["brands"], patches)

    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
