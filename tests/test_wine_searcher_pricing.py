"""Unit tests for volume-aware Wine-Searcher pricing evidence parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from wine_searcher_pricing import (  # noqa: E402
    build_completed_rows,
    extract_offers,
    filter_offers_by_volume,
    parse_product_markdown,
    prepare_evidence,
)


PRODUCT_URL = "https://www.wine-searcher.com/find/dassai+45+junmai+daiginjo+720ml"

PRODUCT_MARKDOWN = """
# Dassai 45 Junmai Daiginjo 720ml

Japan · Sake

**Avg. Price (ex-tax)**

US$ 31 / 720ml
"""

OFFERS_MARKDOWN = """
## Merchant offers

| Merchant | Price | Bottle size |
| --- | ---: | --- |
| Empire Wine | US$ 27.99 | 720ml |
| Local Sake Shop | $16.50 | 375 ml |
| Oak & Vine | USD 33.50 | 0.75 L |
| Unspecified Seller | $29.00 | Size not listed |
"""


class WineSearcherPricingTests(unittest.TestCase):
    def test_parse_product_average_price_and_volume(self) -> None:
        product = parse_product_markdown(PRODUCT_MARKDOWN, PRODUCT_URL)

        self.assertEqual(product["product_title"], "Dassai 45 Junmai Daiginjo 720ml")
        self.assertEqual(product["product_url"], PRODUCT_URL)
        self.assertEqual(product["average_price"], 31.0)
        self.assertEqual(product["average_currency"], "USD")
        self.assertEqual(product["product_volume_ml"], 720)

    def test_extracts_multiple_offers_with_independent_price_and_volume(self) -> None:
        offers = extract_offers(OFFERS_MARKDOWN, PRODUCT_URL)

        self.assertEqual(len(offers), 4)
        self.assertEqual(
            offers[0],
            {
                "merchant_name": "Empire Wine",
                "offer_price": 27.99,
                "currency": "USD",
                "offer_volume_ml": 720,
                "product_url": PRODUCT_URL,
            },
        )
        self.assertEqual(offers[1]["merchant_name"], "Local Sake Shop")
        self.assertEqual(offers[1]["offer_price"], 16.5)
        self.assertEqual(offers[1]["offer_volume_ml"], 375)
        self.assertEqual(offers[2]["offer_volume_ml"], 750)
        self.assertIsNone(offers[3]["offer_volume_ml"])

    def test_only_keeps_offers_with_an_explicit_exact_volume_match(self) -> None:
        offers = extract_offers(OFFERS_MARKDOWN, PRODUCT_URL)

        matching = filter_offers_by_volume(offers, expected_volume_ml=720)

        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["merchant_name"], "Empire Wine")
        self.assertEqual(matching[0]["offer_volume_ml"], 720)

    def test_completed_rows_preserve_every_source_record_and_attach_evidence(self) -> None:
        source_rows = [
            {
                "row_id": "1",
                "parent_sku": "DASSAI-45",
                "parent_name": "Dassai 45 Junmai Daiginjo",
                "parent_volume": "720 ml",
                "provider": "unclefossil",
                "url": "https://unclefossil.example/dassai-45",
            },
            {
                "row_id": "2",
                "parent_sku": "NO-MATCH",
                "parent_name": "Unmatched Sake",
                "parent_volume": "720 ml",
                "provider": "unclefossil",
                "url": "https://unclefossil.example/unmatched",
            },
        ]
        product = parse_product_markdown(PRODUCT_MARKDOWN, PRODUCT_URL)
        matching_offers = filter_offers_by_volume(
            extract_offers(OFFERS_MARKDOWN, PRODUCT_URL), expected_volume_ml=720
        )
        evidence_by_row = {
            "1": {
                "status": "matched",
                "product": product,
                "offers": matching_offers,
            },
            "2": {"status": "not_found", "product": None, "offers": []},
        }

        completed = build_completed_rows(source_rows, evidence_by_row)

        self.assertEqual(len(completed), len(source_rows))
        for source, completed_row in zip(source_rows, completed):
            for field, value in source.items():
                if field in {"provider", "url"}:
                    continue
                self.assertEqual(completed_row[field], value)

        self.assertEqual(completed[0]["provider"], "wine-searcher")
        self.assertEqual(completed[0]["url"], PRODUCT_URL)
        self.assertEqual(completed[1]["provider"], "wine-searcher")
        self.assertIsNone(completed[1]["url"])
        self.assertEqual(completed[0]["wine_searcher_match_status"], "matched")
        self.assertEqual(completed[0]["wine_searcher_average_price"], 31.0)
        self.assertEqual(completed[0]["wine_searcher_average_volume_ml"], 720)
        self.assertIsNone(completed[0]["wine_searcher_avg_price_750ml"])
        self.assertEqual(completed[0]["wine_searcher_offers"], matching_offers)
        self.assertEqual(completed[1]["wine_searcher_match_status"], "not_found")
        self.assertIsNone(completed[1]["wine_searcher_average_price"])
        self.assertEqual(completed[1]["wine_searcher_offers"], [])

    def test_completed_rows_expose_only_a_true_750ml_page_average_in_avg_price_column(self) -> None:
        source = {
            "row_id": "1",
            "parent_sku": "DASSAI-45",
            "parent_name": "Dassai 45 Junmai Daiginjo",
            "parent_volume": "720 ml",
            "url": "https://unclefossil.example/dassai-45",
        }
        evidence = {
            "1": {
                "status": "matched",
                "product": {
                    "product_title": "Dassai 45",
                    "product_url": PRODUCT_URL,
                    "average_price": 36.0,
                    "average_currency": "USD",
                    "product_volume_ml": 750,
                },
                "offers": [],
            }
        }

        completed = build_completed_rows([source], evidence)

        self.assertEqual(completed[0]["wine_searcher_avg_price_750ml"], 36.0)
        self.assertEqual(completed[0]["wine_searcher_avg_price_750ml_currency"], "USD")

    def test_reuses_successful_page_capture_for_a_duplicate_denied_url(self) -> None:
        sources = [
            {
                "name": "Dassai Blue Type 50 Dry Junmai Daiginjo",
                "parent_name": "Dassai Blue Type 50 Dry Junmai Daiginjo",
                "volume(ml)": "375",
            },
            {
                "name": "Dassai Blue Type 50 Dry Junmai Daiginjo",
                "parent_name": "Dassai Blue Type 50 Dry Junmai Daiginjo",
                "volume(ml)": "375",
            },
        ]
        url = "https://www.wine-searcher.com/find/dassai+blue+type+50+dry"
        raw = [
            {
                "source_row_id": "1",
                "requested_url": url,
                "final_url": url,
                "browser_title": "Best local price for Dassai Blue Type 50 Dry",
                "product_title": "Dassai Blue Type 50 Dry",
                "offers": [],
                "search_location": "USA",
            },
            {
                "source_row_id": "2",
                "requested_url": url,
                "browser_title": "Access to this page has been denied",
                "offers": [],
                "search_location": "USA",
            },
        ]

        evidence = prepare_evidence(sources, raw)

        self.assertEqual(evidence["2"]["status"], "matched_no_exact_volume_offer")
        self.assertEqual(evidence["2"]["product"]["product_url"], url)
        self.assertEqual(evidence["2"]["retrieval_method"], "cached_duplicate_url")

    def test_browser_displayed_750ml_average_is_normalized_into_the_dedicated_column(self) -> None:
        source = {
            "row_id": "1",
            "name": "Dassai Blue Type 50",
            "parent_name": "Dassai Blue Type 50",
            "volume(ml)": "375",
        }
        url = "https://www.wine-searcher.com/find/dassai+blue+type+50"
        evidence = prepare_evidence(
            [source],
            [
                {
                    "source_row_id": "1",
                    "requested_url": url,
                    "final_url": url,
                    "browser_title": "Best local price for Dassai Blue Type 50",
                    "product_title": "Dassai Blue Type 50",
                    "average_price": "$31",
                    "average_currency": "$",
                    "average_volume_ml": "750ml",
                    "offers": [],
                    "search_location": "USA",
                }
            ],
        )

        completed = build_completed_rows([source], evidence)

        self.assertEqual(completed[0]["wine_searcher_average_price"], 31.0)
        self.assertEqual(completed[0]["wine_searcher_average_currency"], "USD")
        self.assertEqual(completed[0]["wine_searcher_average_volume_ml"], 750)
        self.assertEqual(completed[0]["wine_searcher_avg_price_750ml"], 31.0)


if __name__ == "__main__":
    unittest.main()
