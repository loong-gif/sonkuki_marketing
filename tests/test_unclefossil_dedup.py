"""Regression tests for the Uncle Fossil product-export deduplication rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from unclefossil_dedup import assess_candidate, group_key, identity_key, process_rows, validate_outputs


PRODUCT_URL = "https://unclefossil.com/products/kubota-senshin-720ml"


def export_row(
    row_id: str,
    parent_name: str,
    parent_sku: str,
    url: str,
    parent_volume: str = "720 ml",
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "parent_name": parent_name,
        "parent_sku": parent_sku,
        "parent_volume": parent_volume,
        "url": url,
    }


class UncleFossilDedupTests(unittest.TestCase):
    def test_duplicate_product_urls_share_a_group(self) -> None:
        first = export_row("1", "Kubota Senshin", "", PRODUCT_URL)
        second = export_row("2", "Kubota Senshin", "", PRODUCT_URL)

        self.assertEqual(group_key(first), group_key(second))

    def test_parent_sku_is_the_group_key_when_present(self) -> None:
        row = export_row("1", "Kubota Senshin", "  KUB-SEN-720  ", PRODUCT_URL)

        self.assertEqual(group_key(row), "sku:KUB-SEN-720")

    def test_category_and_search_urls_are_not_dedup_candidates(self) -> None:
        category = assess_candidate(
            "Junmai Ginjo",
            "Junmai Ginjo",
            "720 ml",
            "https://unclefossil.com/collections/junmai-ginjo",
            "Junmai Ginjo | Uncle Fossil",
        )
        search = assess_candidate(
            "Kubota Senshin",
            "Kubota Senshin",
            "720 ml",
            "https://unclefossil.com/search?q=kubota+senshin",
            "Search results for Kubota Senshin | Uncle Fossil",
        )

        self.assertEqual(category["action"], "reject")
        self.assertEqual(search["action"], "reject")

    def test_explicitly_matching_pdp_title_is_accepted(self) -> None:
        result = assess_candidate(
            "Kubota Senshin",
            "Kubota Senshin",
            "720 ml",
            PRODUCT_URL,
            "Kubota Senshin Junmai Ginjo 720ml | Uncle Fossil",
        )

        self.assertEqual(result["action"], "accept")

    def test_kubota_senshin_is_not_deduplicated_with_kikuhime(self) -> None:
        result = assess_candidate(
            "Kubota Senshin",
            "Kikuhime",
            "720 ml",
            PRODUCT_URL,
            "Kikuhime Junmai Ginjo 720ml | Uncle Fossil",
        )

        self.assertEqual(result["action"], "reject")
        self.assertIn("name", result["reason"])

    def test_aquarius_is_not_deduplicated_with_aries(self) -> None:
        result = assess_candidate(
            "Aquarius",
            "Aries",
            "720 ml",
            "https://unclefossil.com/products/aries-junmai-720ml",
            "Aries Junmai 720ml | Uncle Fossil",
        )

        self.assertEqual(result["action"], "reject")
        self.assertIn("name", result["reason"])

    def test_dassai_blue_50_is_not_deduplicated_with_nigori(self) -> None:
        result = assess_candidate(
            "Dassai Blue 50",
            "Dassai Blue Nigori",
            "720 ml",
            "https://unclefossil.com/products/dassai-blue-nigori-720ml",
            "Dassai Blue Nigori 720ml | Uncle Fossil",
        )

        self.assertEqual(result["action"], "reject")
        self.assertIn("variant", result["reason"])

    def test_shared_producer_name_alone_is_not_a_product_match(self) -> None:
        result = assess_candidate(
            "Kweichow Moutai Bulaojiu 375ml",
            "Moutai 15Yr 375ml",
            "375 ml",
            "https://unclefossil.com/moutai-15yr-375ml.html",
            "Moutai 15Yr 茅台15年 375ml $1899",
        )

        self.assertEqual(result["action"], "reject")
        self.assertIn("name", result["reason"])

    def test_unlabelled_white_variant_is_not_accepted(self) -> None:
        result = assess_candidate(
            "Kubota Seppou White Snow Peak 500ml",
            "Kubota Seppou Snow Peak",
            "500 ml",
            "https://unclefossil.com/kubota-seppou-500ml.html",
            "Kubota Seppou Snow Peak Limited Edition 500ml",
        )

        self.assertEqual(result["action"], "reject")
        self.assertIn("variant", result["reason"])

    def test_blank_skus_do_not_merge_different_parent_products(self) -> None:
        kubota = export_row("1", "Kubota Senshin", "", "")
        kikuhime = export_row("2", "Kikuhime", "", "")

        self.assertNotEqual(group_key(kubota), group_key(kikuhime))

    def test_empty_page_title_is_held_for_review(self) -> None:
        result = assess_candidate(
            "Kubota Senshin",
            "Kubota Senshin",
            "720 ml",
            PRODUCT_URL,
            "",
        )

        self.assertEqual(result["action"], "review")

    def test_single_listing_url_is_strictly_excluded(self) -> None:
        listing = export_row(
            "1",
            "Suigei Ya Junmai Daiginjo 720ml",
            "SUI-YA",
            "https://unclefossil.com/brands/suigei/",
        )
        cleaned, review = process_rows([listing])

        self.assertEqual(cleaned, [])
        self.assertEqual(review[0]["decision"], "unresolved")
        self.assertEqual(review[0]["decision_reason"], "listing_url")

    def test_single_known_404_url_is_strictly_excluded(self) -> None:
        not_found = export_row(
            "1",
            "Unrelated Junmai 720ml",
            "MISSING-PRODUCT",
            "https://unclefossil.com/tanzawasan-yamahai-rinho-cold-mountain-junmai-sake.html",
        )
        cleaned, review = process_rows([not_found])

        self.assertEqual(cleaned, [])
        self.assertEqual(review[0]["decision_reason"], "page_not_found")

    def test_single_known_variant_mismatch_is_strictly_excluded(self) -> None:
        mismatch = export_row(
            "1",
            "Dassai Blue Type 50 Junmai Daiginjo Sample 375ml",
            "DASSAI-SAMPLE",
            "https://unclefossil.com/dassai-blue-type-50-junmai-daiginjo-nigori-sake-37.html",
        )
        cleaned, review = process_rows([mismatch])

        self.assertEqual(cleaned, [])
        self.assertIn(review[0]["decision_reason"], {"name_mismatch", "variant_mismatch"})

    def test_english_title_match_tolerates_different_chinese_style_description(self) -> None:
        result = assess_candidate(
            "Shede Classic Chinese Baijiu 375ml 舍得经典",
            "Shede Classic Chinese Baijiu 375ml",
            "375 ml",
            "https://unclefossil.com/products/shede-classic-375ml",
            "Shede Classic Chinese Baijiu 舍得浓香型白酒 375ml | Uncle Fossil",
        )

        self.assertEqual(result["action"], "accept")

    def test_identity_key_does_not_use_candidate_volume(self) -> None:
        first = {
            **export_row("1", "Unspecified Parent", "PARENT-ONE", PRODUCT_URL, ""),
            "volume(ml)": "375",
        }
        second = {
            **export_row("2", "Unspecified Parent", "PARENT-ONE", PRODUCT_URL, ""),
            "volume(ml)": "720",
        }

        self.assertEqual(identity_key(first), identity_key(second))

    def test_output_validation_conserves_review_rows_and_rejects_duplicate_clean_rows(self) -> None:
        source_rows = [
            export_row("1", "Kubota Senshin", "", PRODUCT_URL),
            export_row("2", "Kubota Senshin", "", PRODUCT_URL),
            export_row("3", "Kikuhime", "", ""),
        ]
        cleaned_rows = [source_rows[0], source_rows[2]]
        review_rows = [
            {**source_rows[0], "selected": True},
            {**source_rows[1], "selected": False},
            {**source_rows[2], "selected": True},
        ]

        self.assertIsNone(validate_outputs(cleaned_rows, review_rows, source_rows))

        duplicate_clean_rows = [source_rows[0], source_rows[1], source_rows[2]]
        duplicate_review_rows = [
            {**source_rows[0], "selected": True},
            {**source_rows[1], "selected": True},
            {**source_rows[2], "selected": True},
        ]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_outputs(duplicate_clean_rows, duplicate_review_rows, source_rows)

        with self.assertRaisesRegex(ValueError, "conservation"):
            validate_outputs(cleaned_rows, review_rows[:-1], source_rows)

    def test_output_validation_keeps_distinct_parent_names_with_colliding_skus(self) -> None:
        source_rows = [
            export_row("1", "Moutai Zodiac Aquarius", "MOUTAI-ZODIAC", "", "500 ml"),
            export_row("2", "Moutai Zodiac Aries", "MOUTAI-ZODIAC", "", "500 ml"),
        ]
        aquarius_identity = "sku:MOUTAI-ZODIAC|name:moutai zodiac aquarius|volume:500ml"
        aries_identity = "sku:MOUTAI-ZODIAC|name:moutai zodiac aries|volume:500ml"
        cleaned_rows = [
            {**source_rows[0], "identity_key": aquarius_identity},
            {**source_rows[1], "identity_key": aries_identity},
        ]
        review_rows = [
            {**source_rows[0], "identity_key": aquarius_identity, "selected": True},
            {**source_rows[1], "identity_key": aries_identity, "selected": True},
        ]

        self.assertEqual(group_key(source_rows[0]), group_key(source_rows[1]))
        self.assertIsNone(validate_outputs(cleaned_rows, review_rows, source_rows))


if __name__ == "__main__":
    unittest.main()
