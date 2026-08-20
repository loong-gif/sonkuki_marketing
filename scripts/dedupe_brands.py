#!/usr/bin/env python3
"""Phase 1: dedupe business keys and backfill products.brand_key.

Tasks:
  link-keys    — dedupe review_listing_links.link_key (keep lowest Id)
  variant-keys — dedupe product_variants.variant_key; repoint listings first
  brand-keys   — backfill empty products.brand_key from variant brand text

Usage:
  python3 scripts/dedupe_brands.py --dry-run [--task all|link-keys|variant-keys|brand-keys]
  python3 scripts/dedupe_brands.py --apply  [--task ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from nocodb_client import TABLES, NocoClient, backup_jsonl, duplicate_record_ids


def norm(value) -> str:
    return str(value or "").strip()


def dedupe_link_keys(client: NocoClient, apply: bool) -> dict:
    table = TABLES["links"]
    rows = client.records(table, ["Id", "link_key", "review_key", "listing_key"])
    kept, dup_ids = duplicate_record_ids(rows, "link_key")
    dup_rows = [r for r in rows if int(r["Id"]) in dup_ids]
    report = {
        "task": "link-keys",
        "total_rows": len(rows),
        "distinct_link_keys": len(kept),
        "duplicate_rows": len(dup_ids),
        "duplicate_ids": dup_ids[:20],
    }
    if dup_ids:
        backup = backup_jsonl(dup_rows, "review_listing_links_dupes_backup")
        report["backup"] = str(backup)
    if apply and dup_ids:
        deleted = client.delete_records(table, dup_ids)
        report["deleted"] = deleted
    return report


def dedupe_variant_keys(client: NocoClient, apply: bool) -> dict:
    table = TABLES["variants"]
    listing_table = TABLES["listings"]
    rows = client.records(table, ["Id", "variant_key", "product_key", "mpn", "brand"])
    kept_map, dup_ids = duplicate_record_ids(rows, "variant_key")
    dup_rows = [r for r in rows if int(r["Id"]) in dup_ids]

    # Map duplicate variant_key -> kept variant_key
    rekey: dict[str, str] = {}
    for row in rows:
        vk = norm(row.get("variant_key"))
        if not vk or vk not in kept_map:
            continue
        kept_id = kept_map[vk]
        if int(row["Id"]) != kept_id:
            rekey[vk] = vk  # same key string; listings reference key not Id

    listings = client.records(listing_table, ["Id", "listing_key", "variant_key"])
    listing_patches = []
    for listing in listings:
        vk = norm(listing.get("variant_key"))
        if vk in kept_map and vk:
            # listings already use variant_key string; no repoint needed unless keys differ
            pass
    # If duplicate rows share the same variant_key string, listings already point to the key.
    # Repoint only when duplicate had a *different* key string (shouldn't happen for true dupes).
    report = {
        "task": "variant-keys",
        "total_rows": len(rows),
        "distinct_variant_keys": len(kept_map),
        "duplicate_rows": len(dup_ids),
        "duplicate_ids": dup_ids,
        "listing_patches": len(listing_patches),
    }
    if dup_ids:
        backup = backup_jsonl(dup_rows, "product_variants_dupes_backup")
        report["backup"] = str(backup)
    if apply:
        if listing_patches:
            client.patch_records(listing_table, listing_patches)
        if dup_ids:
            report["deleted"] = client.delete_records(table, dup_ids)
    return report


def brand_key_from_product_key(product_key: str, name_to_key: dict[str, str]) -> str | None:
    """Extract BRAND:* segment from product_key without inventing new keys."""
    parts = norm(product_key).split(":")
    if len(parts) < 3 or parts[0] != "PRODUCT":
        return None
    if parts[1] == "BRAND" and len(parts) >= 3:
        candidate = f"BRAND:{parts[2]}"
    elif parts[1] == "SONKUKI":
        candidate = "BRAND:SONKUKI"
    elif parts[1].startswith("BRAND"):
        candidate = parts[1] if ":" in parts[1][5:] else f"BRAND:{parts[1].split(':', 1)[-1]}"
    else:
        candidate = f"BRAND:{parts[1]}"
    return name_to_key.get(candidate.upper())


def backfill_brand_keys(client: NocoClient, apply: bool) -> dict:
    products = client.records(TABLES["products"], ["Id", "product_key", "brand_key", "product_name"])
    variant_fields = ["Id", "variant_key", "product_key"]
    variant_meta = {c["title"] for c in client.table_meta(TABLES["variants"]).get("columns", [])}
    if "brand" in variant_meta:
        variant_fields.append("brand")
    variants = client.records(TABLES["variants"], variant_fields)
    brands = client.records(TABLES["brands"], ["Id", "brand_key", "brand_name"])

    name_to_key = {}
    for brand in brands:
        bk = norm(brand.get("brand_key"))
        bn = norm(brand.get("brand_name"))
        if bk:
            name_to_key[bk.upper()] = bk
        if bn:
            name_to_key[bn.upper()] = bk

    by_product: dict[str, list[str]] = defaultdict(list)
    for variant in variants:
        pk = norm(variant.get("product_key"))
        brand_text = norm(variant.get("brand"))
        if pk and brand_text:
            by_product[pk].append(brand_text)

    empty = [p for p in products if not norm(p.get("brand_key"))]
    patches = []
    skipped = []
    for product in empty:
        pk = norm(product.get("product_key"))
        resolved = brand_key_from_product_key(pk, name_to_key)
        if not resolved:
            for candidate in by_product.get(pk, []):
                hit = name_to_key.get(candidate.upper())
                if hit:
                    resolved = hit
                    break
        if resolved:
            patches.append({"Id": product["Id"], "brand_key": resolved})
        else:
            skipped.append({"Id": product["Id"], "product_key": pk, "candidates": by_product.get(pk, [])[:3]})

    report = {
        "task": "brand-keys",
        "empty_brand_key_rows": len(empty),
        "fillable": len(patches),
        "skipped_no_brand_match": len(skipped),
        "skipped_sample": skipped[:5],
    }
    if patches:
        backup = backup_jsonl(patches, "products_brand_key_backfill")
        report["backup"] = str(backup)
    if apply and patches:
        report["patched"] = client.patch_records(TABLES["products"], patches)
    return report


TASKS = {
    "link-keys": dedupe_link_keys,
    "variant-keys": dedupe_variant_keys,
    "brand-keys": backfill_brand_keys,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--task",
        choices=[*TASKS.keys(), "all"],
        default="all",
        help="Which phase-1 task to run (default: all)",
    )
    args = parser.parse_args()
    apply = args.apply
    client = NocoClient()
    client.health()

    tasks = list(TASKS.keys()) if args.task == "all" else [args.task]
    results = []
    for name in tasks:
        result = TASKS[name](client, apply=apply)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    summary = {
        "mode": "apply" if apply else "dry-run",
        "tasks": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
