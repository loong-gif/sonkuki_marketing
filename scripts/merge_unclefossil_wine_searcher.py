"""Build a compact, auditable union of Uncle Fossil and Wine-Searcher prices.

Wine-Searcher is an offer aggregator.  Its rows are added only for merchant
offers whose explicitly displayed bottle size equals both the source product's
volume and the offer's recorded source volume.  Product-level average prices
are intentionally excluded: they are not individual supplier offers.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping


OUTPUT_FIELDS = [
    "parent_sku",
    "parent_name",
    "parent_price",
    "name",
    "price",
    "volume(ml)",
    "provider",
    "url",
]


def _volume(value: object) -> int | None:
    """Read a positive whole-number volume without guessing units."""
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _has_positive_price(value: object) -> bool:
    """Require a numeric price before exposing an offer as accurate data."""
    try:
        return Decimal(str(value).strip().replace(",", "")) > 0
    except (InvalidOperation, ValueError):
        return False


def _source_row(row: Mapping[str, object]) -> dict[str, str]:
    """Return exactly the requested schema for an already-clean source row."""
    return {field: str(row.get(field) or "") for field in OUTPUT_FIELDS}


def build_merged_rows(
    unclefossil_rows: Iterable[Mapping[str, object]], wine_searcher_offers: Iterable[Mapping[str, object]]
) -> list[dict[str, str]]:
    """Append exact-volume Wine-Searcher supplier offers to clean Uncle Fossil rows."""
    source_rows = [_source_row(row) for row in unclefossil_rows]
    by_source_id = {str(index): row for index, row in enumerate(source_rows, start=1)}
    merged = list(source_rows)

    for offer in wine_searcher_offers:
        source = by_source_id.get(str(offer.get("source_row_id") or ""))
        offer_volume = _volume(offer.get("offer_volume_ml"))
        declared_source_volume = _volume(offer.get("source_volume_ml"))
        product_url = str(offer.get("wine_searcher_product_url") or "").strip()
        merchant_url = str(offer.get("offer_url") or "").strip()
        price = str(offer.get("offer_price") or "").strip()
        if (
            source is None
            or offer_volume is None
            or offer_volume != declared_source_volume
            or offer_volume != _volume(source["volume(ml)"])
            or not _has_positive_price(price)
            or not product_url.startswith("https://www.wine-searcher.com/")
        ):
            continue
        # The offer URL is the specific merchant's product page.  Wine-Searcher
        # remains the declared provider and its product page is retained only
        # as a safe fallback when the free offer card exposes no merchant URL.
        output_url = merchant_url if merchant_url.startswith(("https://", "http://")) else product_url
        merged.append(
            {
                "parent_sku": source["parent_sku"],
                "parent_name": source["parent_name"],
                "parent_price": source["parent_price"],
                "name": source["name"],
                "price": price,
                "volume(ml)": str(offer_volume),
                "provider": "wine-searcher",
                "url": output_url,
            }
        )
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unclefossil", type=Path, required=True)
    parser.add_argument("--wine-searcher-offers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.unclefossil.open(encoding="utf-8-sig", newline="") as handle:
        unclefossil_rows = list(csv.DictReader(handle))
    with args.wine_searcher_offers.open(encoding="utf-8-sig", newline="") as handle:
        wine_searcher_offers = list(csv.DictReader(handle))

    merged = build_merged_rows(unclefossil_rows, wine_searcher_offers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(merged)
    print(f"rows={len(merged)}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
