#!/usr/bin/env python3
"""Merge and validate Home Depot review Actor outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("first_page_output", type=Path)
    parser.add_argument("followup_output", type=Path)
    parser.add_argument("residual_output", type=Path)
    parser.add_argument("combined_output", type=Path)
    parser.add_argument("summary_output", type=Path)
    parser.add_argument("product_summary_csv", type=Path)
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    first_page = load_json(args.first_page_output)
    followup = load_json(args.followup_output)
    residual = load_json(args.residual_output)
    records = [*first_page, *followup, *residual]
    args.combined_output.write_text(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    source_by_item = {product["itemId"]: product for product in manifest["products"]}
    records_by_item: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("itemId"):
            records_by_item[record["itemId"]].append(record)

    status_counts = Counter(
        f"{record.get('statusCode')}:{record.get('statusMessage')}" for record in records
    )
    review_keys = [
        (record.get("itemId"), record.get("id"))
        for record in records
        if record.get("statusMessage") == "FOUND" and record.get("id")
    ]
    duplicate_review_keys = len(review_keys) - len(set(review_keys))

    product_summaries: list[dict] = []
    product_rows: list[dict] = []
    complete_found_products = 0
    not_found_products = 0
    products_with_missing_pages: list[str] = []
    total_reported_reviews = 0
    total_scraped_reviews = 0

    for item_id in sorted(source_by_item):
        source = source_by_item[item_id]
        item_records = records_by_item.get(item_id, [])
        found_records = [
            record for record in item_records if record.get("statusMessage") == "FOUND"
        ]
        review_ids = {
            record.get("id") for record in found_records if record.get("id")
        }
        pages = sorted(
            {
                record.get("currentPage")
                for record in found_records
                if record.get("currentPage")
            }
        )
        reported_total = max(
            (record.get("totalResults") or 0 for record in found_records), default=0
        )
        reported_last_page = max(
            (record.get("lastPage") or 0 for record in found_records), default=0
        )
        target_last_page = min(reported_last_page, manifest["maxPagesPerProduct"])
        expected_pages = list(range(1, target_last_page + 1))
        missing_pages = [page for page in expected_pages if page not in pages]
        status = "FOUND" if found_records else "NOT_FOUND"
        if status == "FOUND":
            total_reported_reviews += reported_total
            total_scraped_reviews += len(review_ids)
            if not missing_pages and len(review_ids) == reported_total:
                complete_found_products += 1
            if missing_pages:
                products_with_missing_pages.append(item_id)
        else:
            not_found_products += 1

        summary = {
            "itemId": item_id,
            "mpn": source.get("mpn"),
            "name": source.get("name"),
            "url": source.get("url"),
            "status": status,
            "csvReviewCount": int(source["reviewCountExpected"] or 0),
            "reportedTotalResults": reported_total,
            "scrapedUniqueReviewCount": len(review_ids),
            "reportedLastPage": reported_last_page,
            "pagesScraped": pages,
            "missingPages": missing_pages,
        }
        product_summaries.append(summary)
        product_rows.append(
            {
                "item_id": item_id,
                "mpn": source.get("mpn"),
                "name": source.get("name"),
                "url": source.get("url"),
                "status": status,
                "csv_review_count": source.get("reviewCountExpected"),
                "reported_total_results": reported_total,
                "scraped_unique_review_count": len(review_ids),
                "reported_last_page": reported_last_page,
                "pages_scraped": ",".join(str(page) for page in pages),
                "missing_pages": ",".join(str(page) for page in missing_pages),
            }
        )

    summary = {
        "sourceCsv": manifest["sourceCsv"],
        "actor": manifest["actor"],
        "maxPagesPerProduct": manifest["maxPagesPerProduct"],
        "productCount": len(source_by_item),
        "rawRecordCount": len(records),
        "uniqueReviewCount": len(set(review_keys)),
        "duplicateReviewKeyCount": duplicate_review_keys,
        "totalReportedReviews": total_reported_reviews,
        "totalScrapedUniqueReviews": total_scraped_reviews,
        "statusCounts": dict(status_counts),
        "productsWithCompleteReviewCoverage": complete_found_products,
        "productsNotFound": not_found_products,
        "productsWithMissingPages": products_with_missing_pages,
        "allFoundProductPagesComplete": not products_with_missing_pages,
        "allFoundReviewCountsMatch": total_reported_reviews == total_scraped_reviews,
        "products": product_summaries,
    }
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    fieldnames = list(product_rows[0]) if product_rows else []
    with args.product_summary_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(product_rows)

    print(f"products={len(source_by_item)}")
    print(f"raw_records={len(records)}")
    print(f"unique_reviews={len(set(review_keys))}")
    print(f"complete_found_products={complete_found_products}")
    print(f"not_found_products={not_found_products}")
    print(f"missing_page_products={len(products_with_missing_pages)}")
    print(f"duplicate_review_keys={duplicate_review_keys}")
    print(f"combined={args.combined_output}")
    print(f"summary={args.summary_output}")
    print(f"product_summary={args.product_summary_csv}")


if __name__ == "__main__":
    main()
