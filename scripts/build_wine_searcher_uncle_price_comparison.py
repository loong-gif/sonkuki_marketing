"""Build a one-row-per-product Uncle Fossil and Wine-Searcher price comparison."""

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
    "winesearch price",
    "uncle price",
    "winesearch url",
    "uncle url",
]
def _usd(value: object) -> str:
    """Normalize a positive displayed USD amount, retaining no currency symbol."""
    text = str(value or "").strip().replace("$", "").replace(",", "")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return ""
    return f"{amount:.2f}" if amount > 0 else ""


def _amount(value: object) -> Decimal | None:
    """Parse a positive supplier price for stable lowest-price selection."""
    text = str(value or "").strip().replace("$", "").replace(",", "")
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def _volume(value: object) -> int | None:
    """Parse an explicitly supplied whole-number size."""
    try:
        amount = Decimal(str(value or "").strip())
    except (InvalidOperation, ValueError):
        return None
    return int(amount) if amount > 0 and amount == amount.to_integral_value() else None


def build_comparison_rows(
    uncle_rows: Iterable[Mapping[str, object]], wine_offers: Iterable[Mapping[str, object]]
) -> list[dict[str, str]]:
    """Create one record per product with its lowest exact-volume supplier offer.

    Offers were read in the USA view of Wine-Searcher, so the captured dollar
    amounts are USD even where a free offer card omitted its currency marker.
    """
    offers_by_source_id: dict[str, list[Mapping[str, object]]] = {}
    for offer in wine_offers:
        source_id = str(offer.get("source_row_id") or "").strip()
        if source_id:
            offers_by_source_id.setdefault(source_id, []).append(offer)
    comparison: list[dict[str, str]] = []
    for index, uncle in enumerate(uncle_rows, start=1):
        source_volume = _volume(uncle.get("volume(ml)"))
        candidates = [
            offer
            for offer in offers_by_source_id.get(str(index), [])
            if source_volume is not None
            and _volume(offer.get("source_volume_ml")) == source_volume
            and _volume(offer.get("offer_volume_ml")) == source_volume
            and _amount(offer.get("offer_price")) is not None
        ]
        cheapest = min(candidates, key=lambda offer: _amount(offer.get("offer_price")) or Decimal("Infinity")) if candidates else None
        lowest_price = _usd(cheapest.get("offer_price")) if cheapest else ""
        winesearch_url = ""
        if cheapest:
            merchant_url = str(cheapest.get("offer_url") or "").strip()
            product_url = str(cheapest.get("wine_searcher_product_url") or "").strip()
            winesearch_url = (
                merchant_url
                if merchant_url.startswith(("https://", "http://"))
                else product_url if product_url.startswith("https://www.wine-searcher.com/") else ""
            )
        comparison.append(
            {
                "parent_sku": str(uncle.get("parent_sku") or ""),
                "parent_name": str(uncle.get("parent_name") or ""),
                "parent_price": str(uncle.get("parent_price") or ""),
                "winesearch price": lowest_price,
                "uncle price": _usd(uncle.get("price")),
                "winesearch url": winesearch_url,
                "uncle url": str(uncle.get("url") or "").strip(),
            }
        )
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unclefossil", type=Path, required=True)
    parser.add_argument("--wine-searcher-offers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.unclefossil.open(encoding="utf-8-sig", newline="") as handle:
        uncle_rows = list(csv.DictReader(handle))
    with args.wine_searcher_offers.open(encoding="utf-8-sig", newline="") as handle:
        wine_offers = list(csv.DictReader(handle))
    rows = build_comparison_rows(uncle_rows, wine_offers)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"rows={len(rows)}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
