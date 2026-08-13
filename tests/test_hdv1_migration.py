"""Tests for the deterministic, NocoDB-safe HDV1 transformation rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from hdv1_migration import (  # noqa: E402
    canonical_review,
    classify_segment,
    effective_price,
    parse_dimensions,
    missing_by_business_key,
    duplicate_record_ids,
    raw_business_key,
    review_business_key,
)


class Hdv1TransformationTests(unittest.TestCase):
    def test_raw_key_changes_when_the_source_row_changes(self) -> None:
        first = raw_business_key("mproducts", 14, {"itemId": "101", "name": "A"})
        same = raw_business_key("mproducts", 14, {"name": "A", "itemId": "101"})
        changed = raw_business_key("mproducts", 14, {"itemId": "101", "name": "B"})

        self.assertEqual(first, same)
        self.assertNotEqual(first, changed)

    def test_review_canonicalization_prefers_longest_then_latest(self) -> None:
        chosen, issues = canonical_review(
            [
                {"source_record_id": 2, "reviewText": "short", "collected_at_iso_utc": "2026-08-01T00:00:00Z", "rating": 5},
                {"source_record_id": 1, "reviewText": "longer review", "collected_at_iso_utc": "2026-07-01T00:00:00Z", "rating": 4},
                {"source_record_id": 3, "reviewText": "longer review", "collected_at_iso_utc": "2026-08-02T00:00:00Z", "rating": 5},
            ]
        )

        self.assertEqual(chosen["source_record_id"], 3)
        self.assertIn("REVIEW_RATING_CONFLICT", issues)

    def test_review_key_requires_an_external_id(self) -> None:
        self.assertEqual(review_business_key("123"), "HOME_DEPOT:123")
        self.assertIsNone(review_business_key(""))

    def test_segment_requires_pergola_and_louver_language(self) -> None:
        self.assertEqual(classify_segment("Metal Pergola with Adjustable Louvered Roof"), "DIRECT_LOUVERED")
        self.assertIsNone(classify_segment("Louvered gazebo with hard top"))
        self.assertIsNone(classify_segment("Outdoor pergola with fabric canopy"))

    def test_price_and_dimensions_reject_invalid_values(self) -> None:
        self.assertEqual(effective_price("", "123.45"), 123.45)
        self.assertEqual(effective_price("99", "123.45"), 99.0)
        self.assertIsNone(effective_price("-1", "123.45"))
        self.assertEqual(parse_dimensions("12", "14"), (12.0, 14.0))
        self.assertIsNone(parse_dimensions("0", "14"))

    def test_resume_only_returns_rows_not_already_persisted(self) -> None:
        rows = [{"review_key": "HOME_DEPOT:1"}, {"review_key": "HOME_DEPOT:2"}]

        self.assertEqual(
            missing_by_business_key(rows, "review_key", {"HOME_DEPOT:2"}),
            [{"review_key": "HOME_DEPOT:1"}],
        )

    def test_duplicate_repair_keeps_lowest_record_id_per_business_key(self) -> None:
        rows = [
            {"Id": 8, "link_key": "a"},
            {"Id": 2, "link_key": "a"},
            {"Id": 4, "link_key": "b"},
        ]
        self.assertEqual(duplicate_record_ids(rows, "link_key"), [8])


if __name__ == "__main__":
    unittest.main()
