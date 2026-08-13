#!/usr/bin/env python3
"""Create the one-time, auditable Home Depot Pergola V1 in NocoDB.

Source tables are never mutated.  Run ``--dry-run`` first; ``--apply`` is the
only mode that creates HDV1_ tables or records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from http.client import RemoteDisconnected


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = Path("/private/tmp/hdv1_dry_run_report.json")
BASE_ID = "p447va1t8jqqjty"
API_ROOT = "http://72.52.161.65:8080"
VERSION = "1.0.0"
BATCH_SIZE = 20

SOURCE_SIGNATURES = {
    "listing": {"itemId", "name", "salePrice", "url"},
    "review": {"itemId", "reviewText", "rating"},
    "sales": {"商品名称", "评论总数", "估算销量"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value: Any) -> str:
    return str(value or "").strip()


def numeric(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def effective_price(sale: Any, regular: Any) -> float | None:
    if norm(sale):
        return numeric(sale)
    return numeric(regular)


def parse_dimensions(width: Any, depth: Any) -> tuple[float, float] | None:
    parsed = numeric(width), numeric(depth)
    if any(item is None or item <= 0 for item in parsed):
        return None
    return parsed  # type: ignore[return-value]


def stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def missing_by_business_key(rows: list[dict[str, Any]], key_field: str, existing_keys: set[str]) -> list[dict[str, Any]]:
    """Return the input rows absent from NocoDB, preserving their order."""
    return [row for row in rows if norm(row.get(key_field)) not in existing_keys]


def duplicate_record_ids(rows: list[dict[str, Any]], key_field: str) -> list[int]:
    """Return duplicate NocoDB record IDs, retaining the lowest ID per key."""
    kept: dict[str, int] = {}
    duplicates: list[int] = []
    for row in sorted(rows, key=lambda item: int(item["Id"])):
        key = norm(row.get(key_field))
        if not key:
            continue
        if key in kept:
            duplicates.append(int(row["Id"]))
        else:
            kept[key] = int(row["Id"])
    return duplicates


def raw_business_key(source_table_id: str, source_record_id: Any, row: dict[str, Any]) -> str:
    digest = hashlib.sha256(stable_json(row).encode("utf-8")).hexdigest()
    return f"{source_table_id}:{source_record_id}:{digest}"


def review_business_key(external_review_id: Any) -> str | None:
    review_id = norm(external_review_id)
    return f"HOME_DEPOT:{review_id}" if review_id else None


def source_review_id(row: dict[str, Any]) -> Any:
    """NocoDB renamed the imported CSV's ``id`` to ``id1``."""
    return row.get("id") or row.get("id1")


def classify_segment(title: Any) -> str | None:
    text = norm(title).lower()
    louvered = "louvered" in text or "adjustable louver" in text
    return "DIRECT_LOUVERED" if "pergola" in text and louvered else None


def canonical_review(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], set[str]]:
    ranked = sorted(
        rows,
        key=lambda row: (len(norm(row.get("reviewText"))), norm(row.get("collected_at_iso_utc")), -int(row.get("source_record_id") or 0)),
        reverse=True,
    )
    chosen = ranked[0]
    issues: set[str] = set()
    for field, code in (("rating", "REVIEW_RATING_CONFLICT"), ("time", "REVIEW_DATE_CONFLICT"), ("userName", "REVIEWER_CONFLICT"), ("reviewText", "REVIEW_TEXT_CONFLICT")):
        if len({norm(row.get(field)) for row in rows if norm(row.get(field))}) > 1:
            issues.add(code)
    return chosen, issues


@dataclass(frozen=True)
class SourceTable:
    kind: str
    id: str
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]


class NocoClient:
    def __init__(self) -> None:
        token = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
        self.headers = {"xc-token": token, "accept": "application/json"}
        self.opener = build_opener(ProxyHandler({}))

    def request(self, method: str, path: str, payload: Any = None, retries: int = 4) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with self.opener.open(Request(API_ROOT + path, data=body, headers=headers, method=method), timeout=45) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
            except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected, socket.timeout) as exc:
                last = exc
                if attempt + 1 == retries:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError(f"NocoDB {method} {path} failed: {last}")

    def tables(self) -> list[dict[str, Any]]:
        return self.request("GET", f"/api/v2/meta/bases/{BASE_ID}/tables").get("list", [])

    def table_meta(self, table_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v2/meta/tables/{table_id}")

    def records(self, table_id: str, fields: list[str] | None = None) -> list[dict[str, Any]]:
        result, offset = [], 0
        while True:
            params: dict[str, Any] = {"limit": 250, "offset": offset}
            if fields:
                params["fields"] = ",".join(fields)
            page = self.request("GET", f"/api/v2/tables/{table_id}/records?{urlencode(params)}").get("list", [])
            result.extend(page)
            print(f"read {table_id}: {len(result)} records", flush=True)
            if len(page) < 250:
                return result
            offset += len(page)

    def create_table(self, title: str, columns: list[tuple[str, str]]) -> str:
        payload = {"title": title, "table_name": title, "columns": [{"title": name, "column_name": re.sub(r"[^a-z0-9_]", "_", name.lower()), "uidt": uidt} for name, uidt in columns]}
        return self.request("POST", f"/api/v2/meta/bases/{BASE_ID}/tables", payload)["id"]

    def existing_keys(self, table_id: str, key_field: str) -> set[str]:
        return {norm(row.get(key_field)) for row in self.records(table_id, [key_field]) if norm(row.get(key_field))}

    def delete_records(self, table_id: str, record_ids: list[int]) -> None:
        # NocoDB v2 deletes record batches from the collection endpoint.
        self.request("DELETE", f"/api/v2/tables/{table_id}/records", [{"Id": record_id} for record_id in record_ids], retries=1)

    def insert_missing(self, table_id: str, rows: list[dict[str, Any]], key_field: str, batch_size: int = BATCH_SIZE) -> int:
        """Resume safely even if a prior POST timed out after server-side commit.

        A POST gets one network attempt.  On any uncertain outcome, target keys
        are re-read and only missing rows are retried in smaller batches.
        """
        existing = self.existing_keys(table_id, key_field)
        pending = missing_by_business_key(rows, key_field, existing)
        inserted = 0
        consecutive_uncertain_writes = 0
        while pending:
            batch = pending[:batch_size]
            try:
                self.request("POST", f"/api/v2/tables/{table_id}/records", batch, retries=1)
            except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected, socket.timeout):
                existing = self.existing_keys(table_id, key_field)
                resumed = missing_by_business_key(pending, key_field, existing)
                if len(resumed) < len(pending):
                    consecutive_uncertain_writes = 0
                else:
                    consecutive_uncertain_writes += 1
                pending = resumed
                if batch_size > 1:
                    batch_size = max(1, batch_size // 2)
                    continue
                if consecutive_uncertain_writes >= 12:
                    raise RuntimeError(f"NocoDB repeatedly rejected a single-record write to {table_id}")
                time.sleep(min(30, consecutive_uncertain_writes * 2))
                continue
            inserted += len(batch)
            pending = pending[len(batch):]
        return inserted


def discover_sources(client: NocoClient) -> dict[str, SourceTable]:
    # Target/analytics tables (renamed from HDV1_* to snake_case on 2026-08-13).
    TARGET_TITLES = {"brands", "products", "product_variants", "product_listings",
                     "reviews", "review_listing_links", "listing_snapshots",
                     "raw_listing_snapshots", "ingestion_runs", "source_registry"}
    found: dict[str, SourceTable] = {}
    for table in client.tables():
        if table.get("title", "") in TARGET_TITLES:
            continue
        meta = client.table_meta(table["id"])
        columns = [column.get("title") for column in meta.get("columns", []) if column.get("title")]
        for kind, signature in SOURCE_SIGNATURES.items():
            compatible = signature.issubset(columns) and (kind != "review" or "id1" in columns or "id" in columns)
            if compatible:
                if kind in found:
                    raise RuntimeError(f"ambiguous {kind} sources: {found[kind].title}, {table['title']}")
                print(f"reading source {kind}: {table['title']}", flush=True)
                review_fields = {"Id", "id", "id1", "itemId", "title", "reviewText", "rating", "time", "userName", "productId", "productName"}
                source_fields = columns if kind != "review" else [field for field in columns if field in review_fields]
                found[kind] = SourceTable(kind, table["id"], table["title"], columns, client.records(table["id"], source_fields))
    missing = sorted(set(SOURCE_SIGNATURES) - set(found))
    if missing:
        raise RuntimeError(f"required Home Depot source tables not found: {', '.join(missing)}")
    return found


def dry_run_report(sources: dict[str, SourceTable]) -> dict[str, Any]:
    listings, reviews = sources["listing"].rows, sources["review"].rows
    review_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reviews:
        key = review_business_key(source_review_id(row))
        if key:
            review_groups[key].append({**row, "source_record_id": row.get("Id"), "collected_at_iso_utc": utc_now()})
    invalid_dimensions = sum(parse_dimensions(row.get("specifications|Approximate Width (ft.)"), row.get("specifications|Approximate Depth (ft.)")) is None for row in listings)
    return {
        "version": VERSION,
        "generated_at_iso_utc": utc_now(),
        "source_tables": {kind: {"id": item.id, "title": item.title, "columns": item.columns, "row_count": len(item.rows)} for kind, item in sources.items()},
        "listing_quality": {"missing_item_id": sum(not norm(row.get("itemId")) for row in listings), "invalid_dimensions": invalid_dimensions, "direct_louvered": sum(classify_segment(row.get("name")) == "DIRECT_LOUVERED" for row in listings)},
        "review_quality": {"missing_external_id": sum(review_business_key(source_review_id(row)) is None for row in reviews), "canonical_reviews": len(review_groups), "cross_listing_review_ids": sum(len({norm(row.get("itemId")) for row in rows}) > 1 for rows in review_groups.values())},
    }


TABLES: dict[str, list[tuple[str, str]]] = {
    "HDV1_Ingestion_Runs": [("run_key", "SingleLineText"), ("status", "SingleLineText"), ("script_version", "SingleLineText"), ("started_at_iso_utc", "SingleLineText"), ("completed_at_iso_utc", "SingleLineText"), ("read_rows", "Number"), ("written_rows", "Number"), ("rejected_rows", "Number")],
    "HDV1_Source_Registry": [("source_key", "SingleLineText"), ("source_table_id", "SingleLineText"), ("source_table_title", "SingleLineText"), ("field_list_json", "LongText"), ("row_count", "Number"), ("extracted_at_iso_utc", "SingleLineText"), ("migration_version", "SingleLineText")],
    "HDV1_Raw_Listing_Snapshots": [("raw_key", "SingleLineText"), ("source_table_id", "SingleLineText"), ("source_record_id", "Number"), ("payload_json", "LongText"), ("source_url", "URL"), ("observed_at_iso_utc", "SingleLineText")],
    "HDV1_Raw_Review_Observations": [("raw_key", "SingleLineText"), ("source_table_id", "SingleLineText"), ("source_record_id", "Number"), ("external_review_id", "SingleLineText"), ("payload_json", "LongText"), ("observed_at_iso_utc", "SingleLineText")],
    "HDV1_Raw_Sales_Observations": [("raw_key", "SingleLineText"), ("source_table_id", "SingleLineText"), ("source_record_id", "Number"), ("payload_json", "LongText"), ("observed_at_iso_utc", "SingleLineText")],
    "HDV1_Brands": [("brand_key", "SingleLineText"), ("brand_name", "SingleLineText")],
    "HDV1_Products": [("product_key", "SingleLineText"), ("brand_key", "SingleLineText"), ("product_name", "LongText")],
    "HDV1_Product_Variants": [("variant_key", "SingleLineText"), ("product_key", "SingleLineText"), ("mpn", "SingleLineText"), ("width_ft", "Number"), ("depth_ft", "Number"), ("color", "SingleLineText")],
    "HDV1_Channel_Listings": [("listing_key", "SingleLineText"), ("external_listing_id", "SingleLineText"), ("external_parent_id", "SingleLineText"), ("variant_key", "SingleLineText"), ("listing_title", "LongText"), ("listing_url", "URL"), ("is_super_sku", "Checkbox")],
    "HDV1_Listing_Snapshots": [("snapshot_key", "SingleLineText"), ("listing_key", "SingleLineText"), ("observed_at_iso_utc", "SingleLineText"), ("regular_price", "Number"), ("sale_price", "Number"), ("effective_price", "Number"), ("review_count", "Number"), ("avg_rating", "Number"), ("is_in_stock", "Checkbox"), ("inventory_quantity", "Number"), ("price_per_sq_ft", "Number")],
    "HDV1_Customer_Reviews": [("review_key", "SingleLineText"), ("external_review_id", "SingleLineText"), ("review_date_iso_utc", "SingleLineText"), ("rating", "Number"), ("review_title", "LongText"), ("review_text", "LongText"), ("reviewer_display_name", "SingleLineText")],
    "HDV1_Review_Listing_Links": [("link_key", "SingleLineText"), ("review_key", "SingleLineText"), ("listing_key", "SingleLineText")],
    "HDV1_Market_Segments": [("segment_key", "SingleLineText"), ("segment_name", "SingleLineText")],
    "HDV1_Listing_Segments": [("listing_segment_key", "SingleLineText"), ("listing_key", "SingleLineText"), ("segment_key", "SingleLineText")],
    "HDV1_Sales_Estimation_Scenarios": [("scenario_key", "SingleLineText"), ("listing_key", "SingleLineText"), ("method", "SingleLineText"), ("method_version", "SingleLineText"), ("estimated_sales_low", "Number"), ("estimated_sales_base", "Number"), ("estimated_sales_high", "Number")],
    "HDV1_Data_Quality_Issues": [("issue_key", "SingleLineText"), ("issue_code", "SingleLineText"), ("entity_key", "SingleLineText"), ("detail_json", "LongText"), ("status", "SingleLineText")],
}


def ensure_tables(client: NocoClient) -> dict[str, str]:
    existing = {table["title"]: table["id"] for table in client.tables()}
    for title, columns in TABLES.items():
        if title not in existing:
            print(f"creating {title}", flush=True)
            existing[title] = client.create_table(title, columns)
    return {title: existing[title] for title in TABLES}


def apply_migration(client: NocoClient, sources: dict[str, SourceTable], report: dict[str, Any]) -> None:
    table_ids = ensure_tables(client)
    def write(table_name: str, rows: list[dict[str, Any]], key_field: str, batch_size: int = BATCH_SIZE) -> int:
        if not rows:
            return 0
        inserted = client.insert_missing(table_ids[table_name], rows, key_field, batch_size)
        print(f"{table_name}: inserted {inserted}, total target rows {len(rows)}", flush=True)
        return inserted

    run_key, observed = f"HDV1:{utc_now()}", utc_now()
    write("HDV1_Ingestion_Runs", [{"run_key": run_key, "status": "COMPLETED", "script_version": VERSION, "started_at_iso_utc": observed, "completed_at_iso_utc": utc_now(), "read_rows": sum(len(source.rows) for source in sources.values()), "written_rows": 0, "rejected_rows": report["listing_quality"]["missing_item_id"]}], "run_key")
    write("HDV1_Source_Registry", [{"source_key": source.id, "source_table_id": source.id, "source_table_title": source.title, "field_list_json": json.dumps(source.columns, ensure_ascii=False), "row_count": len(source.rows), "extracted_at_iso_utc": observed, "migration_version": VERSION} for source in sources.values()], "source_key")
    listings = sources["listing"]
    raw_listings, brands, products, variants, channel_listings, snapshots, segments, listing_segments, issues = [], {}, {}, {}, [], [], [{"segment_key": "DIRECT_LOUVERED", "segment_name": "Direct Louvered"}], [], []
    for row in listings.rows:
        raw_key = raw_business_key(listings.id, row["Id"], row)
        raw_listings.append({"raw_key": raw_key, "source_table_id": listings.id, "source_record_id": row["Id"], "payload_json": stable_json(row), "source_url": norm(row.get("url")), "observed_at_iso_utc": observed})
        item_id = norm(row.get("itemId"))
        if not item_id:
            issues.append({"issue_key": f"MISSING_ITEM_ID:{raw_key}", "issue_code": "MISSING_ITEM_ID", "entity_key": raw_key, "detail_json": stable_json(row), "status": "OPEN"}); continue
        listing_key, brand_name, mpn = f"HOME_DEPOT:{item_id}", norm(row.get("brand|slogan")) or "UNKNOWN", norm(row.get("mpn"))
        brand_key = f"BRAND:{brand_name.upper()}"; brands[brand_key] = {"brand_key": brand_key, "brand_name": brand_name}
        product_key = f"PRODUCT:{brand_key}:{mpn or item_id}"; products[product_key] = {"product_key": product_key, "brand_key": brand_key, "product_name": norm(row.get("name"))}
        dimensions = parse_dimensions(row.get("specifications|Approximate Width (ft.)"), row.get("specifications|Approximate Depth (ft.)"))
        if not dimensions: issues.append({"issue_key": f"INVALID_DIMENSIONS:{listing_key}", "issue_code": "INVALID_DIMENSIONS", "entity_key": listing_key, "detail_json": stable_json(row), "status": "OPEN"})
        variant_key = f"VARIANT:{mpn or item_id}"; variants[variant_key] = {"variant_key": variant_key, "product_key": product_key, "mpn": mpn, "width_ft": dimensions[0] if dimensions else None, "depth_ft": dimensions[1] if dimensions else None, "color": norm(row.get("specifications|Color Family"))}
        channel_listings.append({"listing_key": listing_key, "external_listing_id": item_id, "external_parent_id": norm(row.get("parentId")), "variant_key": variant_key, "listing_title": norm(row.get("name")), "listing_url": norm(row.get("url")), "is_super_sku": bool(row.get("isSuperSku"))})
        price = effective_price(row.get("salePrice"), row.get("originalPrice")); area = dimensions[0] * dimensions[1] if dimensions else None
        snapshots.append({"snapshot_key": f"{listing_key}:{observed}", "listing_key": listing_key, "observed_at_iso_utc": observed, "regular_price": numeric(row.get("originalPrice")), "sale_price": numeric(row.get("salePrice")), "effective_price": price, "review_count": numeric(row.get("reviewCount")), "avg_rating": numeric(row.get("rating")), "is_in_stock": bool(row.get("inventory|isInStock")), "inventory_quantity": numeric(row.get("inventory|quantity")), "price_per_sq_ft": price / area if price is not None and area else None})
        if classify_segment(row.get("name")):
            listing_segments.append({"listing_segment_key": f"{listing_key}:DIRECT_LOUVERED", "listing_key": listing_key, "segment_key": "DIRECT_LOUVERED"})
    write("HDV1_Raw_Listing_Snapshots", raw_listings, "raw_key", 5); write("HDV1_Brands", list(brands.values()), "brand_key"); write("HDV1_Products", list(products.values()), "product_key"); write("HDV1_Product_Variants", list(variants.values()), "variant_key"); write("HDV1_Channel_Listings", channel_listings, "listing_key"); write("HDV1_Listing_Snapshots", snapshots, "listing_key"); write("HDV1_Market_Segments", segments, "segment_key"); write("HDV1_Listing_Segments", listing_segments, "listing_segment_key")
    reviews = sources["review"]; groups: dict[str, list[dict[str, Any]]] = defaultdict(list); raw_reviews = []
    for row in reviews.rows:
        external_id = source_review_id(row); raw_key = raw_business_key(reviews.id, row["Id"], row); raw_reviews.append({"raw_key": raw_key, "source_table_id": reviews.id, "source_record_id": row["Id"], "external_review_id": norm(external_id), "payload_json": stable_json(row), "observed_at_iso_utc": observed}); key = review_business_key(external_id)
        if key: groups[key].append({**row, "source_record_id": row["Id"], "collected_at_iso_utc": observed})
    canonical, links = [], []
    for key, rows in groups.items():
        selected, conflict_codes = canonical_review(rows); canonical.append({"review_key": key, "external_review_id": norm(source_review_id(selected)), "review_date_iso_utc": norm(selected.get("time")), "rating": numeric(selected.get("rating")), "review_title": norm(selected.get("title")), "review_text": norm(selected.get("reviewText")), "reviewer_display_name": norm(selected.get("userName"))})
        for item_id in {norm(row.get("itemId")) for row in rows if norm(row.get("itemId"))}: links.append({"link_key": f"{key}:HOME_DEPOT:{item_id}", "review_key": key, "listing_key": f"HOME_DEPOT:{item_id}"})
        for code in conflict_codes: issues.append({"issue_key": f"{code}:{key}", "issue_code": code, "entity_key": key, "detail_json": "{}", "status": "OPEN"})
    sales = sources["sales"]
    raw_sales = [{"raw_key": raw_business_key(sales.id, row["Id"], row), "source_table_id": sales.id, "source_record_id": row["Id"], "payload_json": stable_json(row), "observed_at_iso_utc": observed} for row in sales.rows]
    write("HDV1_Raw_Review_Observations", raw_reviews, "raw_key", 5); write("HDV1_Customer_Reviews", canonical, "review_key", 20); write("HDV1_Review_Listing_Links", links, "link_key", 20); write("HDV1_Raw_Sales_Observations", raw_sales, "raw_key", 10); write("HDV1_Data_Quality_Issues", issues, "issue_key", 10)


def resume_review_listing_links(client: NocoClient, sources: dict[str, SourceTable]) -> None:
    """Resume only the relation table after an interrupted full import."""
    table_ids = ensure_tables(client)
    groups: dict[str, set[str]] = defaultdict(set)
    for row in sources["review"].rows:
        review_key = review_business_key(source_review_id(row))
        item_id = norm(row.get("itemId"))
        if review_key and item_id:
            groups[review_key].add(item_id)
    links = [
        {"link_key": f"{review_key}:HOME_DEPOT:{item_id}", "review_key": review_key, "listing_key": f"HOME_DEPOT:{item_id}"}
        for review_key, item_ids in groups.items()
        for item_id in sorted(item_ids)
    ]
    inserted = client.insert_missing(table_ids["HDV1_Review_Listing_Links"], links, "link_key", 20)
    print(json.dumps({"mode": "resume-links", "expected": len(links), "inserted": inserted}, ensure_ascii=False))


def repair_duplicate_review_listing_links(client: NocoClient, apply: bool) -> None:
    table_ids = ensure_tables(client)
    table_id = table_ids["HDV1_Review_Listing_Links"]
    duplicates = duplicate_record_ids(client.records(table_id, ["Id", "link_key"]), "link_key")
    if not apply:
        print(json.dumps({"mode": "dedupe-links-preview", "duplicate_record_count": len(duplicates), "record_ids": duplicates}, ensure_ascii=False))
        return
    original_count = len(duplicates)
    failures = 0
    while duplicates:
        try:
            client.delete_records(table_id, duplicates[:20])
            failures = 0
        except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected, socket.timeout):
            failures += 1
            if failures >= 12:
                raise RuntimeError("NocoDB repeatedly closed the duplicate-link deletion connection")
            time.sleep(min(30, failures * 2))
        duplicates = duplicate_record_ids(client.records(table_id, ["Id", "link_key"]), "link_key")
        print(f"duplicate links remaining: {len(duplicates)}", flush=True)
    print(json.dumps({"mode": "dedupe-links-apply", "deleted_duplicate_record_count": original_count}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--inventory", action="store_true")
    mode.add_argument("--resume-links", action="store_true")
    mode.add_argument("--dedupe-links-preview", action="store_true")
    mode.add_argument("--dedupe-links-apply", action="store_true")
    args = parser.parse_args()
    client = NocoClient()
    if args.inventory:
        inventory = []
        for table in client.tables():
            meta = client.table_meta(table["id"])
            inventory.append({"id": table["id"], "title": table.get("title"), "columns": [column.get("title") for column in meta.get("columns", []) if column.get("title")]})
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return
    if args.dedupe_links_preview:
        repair_duplicate_review_listing_links(client, apply=False)
        return
    if args.dedupe_links_apply:
        repair_duplicate_review_listing_links(client, apply=True)
        return
    sources = discover_sources(client)
    report = dry_run_report(sources)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps({"mode": "dry-run", "report": str(REPORT_PATH), **report}, ensure_ascii=False))
        return
    if args.resume_links:
        resume_review_listing_links(client, sources)
        return
    apply_migration(client, sources, report)
    print(json.dumps({"mode": "apply", "status": "completed", "report": str(REPORT_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
