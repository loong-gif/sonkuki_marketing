"""Tests for the one-row-per-product price comparison export."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from build_wine_searcher_uncle_price_comparison import (  # noqa: E402
    OUTPUT_FIELDS,
    build_comparison_rows,
)


class WineSearcherUnclePriceComparisonTests(unittest.TestCase):
    def test_uses_the_lowest_exact_volume_supplier_price_and_its_url(self) -> None:
        uncle_rows = [
            {
                "parent_sku": "SKU-1",
                "parent_name": "Dassai 45",
                "parent_price": "35.00",
                "price": "$32.00",
                "volume(ml)": "720",
                "url": "https://www.unclefossil.com/dassai-45.html",
            }
        ]
        wine_offers = [
            {
                "source_row_id": "1",
                "source_volume_ml": "720",
                "offer_volume_ml": "720",
                "offer_price": "81.00",
                "offer_url": "https://merchant.example/dassai-45-81",
                "wine_searcher_product_url": "https://www.wine-searcher.com/find/dassai+45",
            },
            {
                "source_row_id": "1",
                "source_volume_ml": "720",
                "offer_volume_ml": "720",
                "offer_price": "29.50",
                "offer_url": "https://merchant.example/dassai-45-29-50",
                "wine_searcher_product_url": "https://www.wine-searcher.com/find/dassai+45",
            },
        ]

        rows = build_comparison_rows(uncle_rows, wine_offers)

        self.assertEqual(
            rows,
            [
                {
                    "parent_sku": "SKU-1",
                    "parent_name": "Dassai 45",
                    "parent_price": "35.00",
                    "winesearch price": "29.50",
                    "uncle price": "32.00",
                    "winesearch url": "https://merchant.example/dassai-45-29-50",
                    "uncle url": "https://www.unclefossil.com/dassai-45.html",
                }
            ],
        )
        self.assertEqual(list(rows[0]), OUTPUT_FIELDS)

    def test_leaves_winesearch_price_blank_without_an_exact_volume_supplier_offer(self) -> None:
        uncle_rows = [{"parent_sku": "SKU-1", "parent_name": "Product", "parent_price": "20", "price": "$19", "volume(ml)": "720"}]
        wine_offers = [
            {
                "source_row_id": "1",
                "source_volume_ml": "720",
                "offer_volume_ml": "375",
                "offer_price": "50",
            }
        ]

        rows = build_comparison_rows(uncle_rows, wine_offers)

        self.assertEqual(rows[0]["winesearch price"], "")
        self.assertEqual(rows[0]["winesearch url"], "")
        self.assertEqual(rows[0]["uncle price"], "19.00")

    def test_does_not_shift_rows_when_winesearch_evidence_is_missing(self) -> None:
        uncle_rows = [
            {"parent_sku": "SKU-1", "parent_name": "First", "parent_price": "20", "price": "$19", "volume(ml)": "720"},
            {"parent_sku": "SKU-2", "parent_name": "Second", "parent_price": "30", "price": "$29", "volume(ml)": "720"},
        ]

        rows = build_comparison_rows(uncle_rows, [])

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["parent_sku"], "SKU-1")
        self.assertEqual(rows[1]["parent_sku"], "SKU-2")
        self.assertEqual(rows[1]["winesearch price"], "")


if __name__ == "__main__":
    unittest.main()
