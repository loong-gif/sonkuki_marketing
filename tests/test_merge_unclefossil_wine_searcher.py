"""Tests for the eight-column Uncle Fossil/Wine-Searcher union export."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from merge_unclefossil_wine_searcher import OUTPUT_FIELDS, build_merged_rows  # noqa: E402


class MergeUncleFossilWineSearcherTests(unittest.TestCase):
    def test_unites_clean_unclefossil_rows_with_exact_volume_wine_searcher_offers(self) -> None:
        unclefossil_rows = [
            {
                "parent_sku": "SKU-1",
                "parent_name": "Dassai 45",
                "parent_price": "35.00",
                "name": "Dassai 45 Junmai Daiginjo 720ml",
                "price": "32.00",
                "volume(ml)": "720",
                "provider": "unclefossil",
                "url": "https://www.unclefossil.com/dassai-45.html",
            }
        ]
        offers = [
            {
                "source_row_id": "1",
                "source_volume_ml": "720",
                "offer_volume_ml": "720",
                "offer_price": "27.99",
                "offer_url": "https://merchant.example/dassai-45-720ml",
                "wine_searcher_product_url": "https://www.wine-searcher.com/find/dassai+45",
            },
            {
                "source_row_id": "1",
                "source_volume_ml": "720",
                "offer_volume_ml": "375",
                "offer_price": "16.50",
                "wine_searcher_product_url": "https://www.wine-searcher.com/find/dassai+45",
            },
        ]

        rows = build_merged_rows(unclefossil_rows, offers)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], unclefossil_rows[0])
        self.assertEqual(
            rows[1],
            {
                "parent_sku": "SKU-1",
                "parent_name": "Dassai 45",
                "parent_price": "35.00",
                "name": "Dassai 45 Junmai Daiginjo 720ml",
                "price": "27.99",
                "volume(ml)": "720",
                "provider": "wine-searcher",
                "url": "https://merchant.example/dassai-45-720ml",
            },
        )
        self.assertEqual(list(rows[0]), OUTPUT_FIELDS)

    def test_excludes_missing_or_invalid_wine_searcher_prices(self) -> None:
        unclefossil_rows = [
            {
                "parent_sku": "SKU-1",
                "parent_name": "Product",
                "parent_price": "20",
                "name": "Product 750ml",
                "price": "20",
                "volume(ml)": "750",
                "provider": "unclefossil",
                "url": "https://www.unclefossil.com/product.html",
            }
        ]
        offers = [
            {
                "source_row_id": "1",
                "source_volume_ml": "750",
                "offer_volume_ml": "750",
                "offer_price": "",
                "wine_searcher_product_url": "https://www.wine-searcher.com/find/product",
            },
            {
                "source_row_id": "999",
                "source_volume_ml": "750",
                "offer_volume_ml": "750",
                "offer_price": "30.00",
                "wine_searcher_product_url": "https://www.wine-searcher.com/find/product",
            },
        ]

        rows = build_merged_rows(unclefossil_rows, offers)

        self.assertEqual(rows, unclefossil_rows)


if __name__ == "__main__":
    unittest.main()
