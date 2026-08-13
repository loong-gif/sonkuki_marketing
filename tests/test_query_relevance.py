"""Unit tests for the GSC query relevance classification rules.

Mirrors irrelevant_query_clean.md: four rules map every query to
VALID / IRRELEVANT / UNKNOWN, and only VALID rows enter the Clean Query
Dataset used by Keyword Opportunity.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from query_relevance import (
    BRAND_RE,
    IRRELEVANT,
    PRODUCT_TERMS,
    UNKNOWN,
    VALID,
    build_clean_dataset,
    classify_relevance,
    classify_row,
    normalize_query,
)


class NormalizeTests(unittest.TestCase):
    def test_lowercase_and_trim(self) -> None:
        self.assertEqual(normalize_query("  SONKUKI  Pergola  "), "sonkuki pergola")

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_query("patio\n  umbrella\tbase"), "patio umbrella base")


class RuleOneBrandTests(unittest.TestCase):
    def test_brand_variants_are_valid(self) -> None:
        for query in ("sonkuki", "sonuki", "sankuki", "son uki", "zimi america", "bonosuki"):
            status, reason = classify_relevance(query)
            self.assertEqual(status, VALID, query)
            self.assertEqual(reason, "BRAND", query)

    def test_brand_plus_product_is_brand_product(self) -> None:
        status, reason = classify_relevance("sonkuki pergola")
        self.assertEqual((status, reason), (VALID, "BRAND_PRODUCT"))


class RuleTwoProductTests(unittest.TestCase):
    def test_document_examples_are_valid_product(self) -> None:
        for query in ("patio umbrella", "cantilever umbrella", "led umbrella", "umbrella base",
                      "patio furniture", "outdoor furniture", "outdoor dining", "pergola",
                      "louvered pergola", "pergola screen"):
            status, reason = classify_relevance(query)
            self.assertEqual((status, reason), (VALID, "PRODUCT"), query)

    def test_extended_category_terms_are_valid(self) -> None:
        for query in ("adjustable adirondack chair with retractable ottoman", "patio parasols for sale",
                      "how to lubricate umbrella", "eco friendly patio furniture", "market umbrellas berwick"):
            status, _ = classify_relevance(query)
            self.assertEqual(status, VALID, query)


class RuleThreeCompetitorTests(unittest.TestCase):
    def test_competitor_brands_are_valid(self) -> None:
        # Product terms are checked before competitor/retailer per the doc's
        # rule order, so a brand+product query is VALID either way.
        for query in ("purple leaf pergola", "purple leaf"):
            status, _ = classify_relevance(query)
            self.assertEqual(status, VALID, query)

    def test_retailers_are_valid(self) -> None:
        for query in ("home depot patio umbrella", "home depot", "walmart delivery"):
            status, _ = classify_relevance(query)
            self.assertEqual(status, VALID, query)


class RuleFourIrrelevantTests(unittest.TestCase):
    def test_document_example_is_irrelevant(self) -> None:
        status, reason = classify_relevance("randomsite.com customer service phone number")
        self.assertEqual((status, reason), (IRRELEVANT, "UNRELATED_SUPPORT_QUERY"))

    def test_rule_four_outranks_product_terms(self) -> None:
        status, reason = classify_relevance("someothersite.net umbrella customer service phone number")
        self.assertEqual((status, reason), (IRRELEVANT, "UNRELATED_SUPPORT_QUERY"))

    def test_own_brand_support_query_is_not_irrelevant(self) -> None:
        status, _ = classify_relevance("sonkuki customer service phone number")
        self.assertEqual(status, VALID)


class UnknownTests(unittest.TestCase):
    def test_no_rule_match_is_unknown(self) -> None:
        status, reason = classify_relevance("unknown phrase")
        self.assertEqual((status, reason), (UNKNOWN, "NO_RULE_MATCH"))

    def test_bare_domain_without_service_terms_is_unknown(self) -> None:
        status, _ = classify_relevance("kuki.com")
        self.assertEqual(status, UNKNOWN)


class DatasetTests(unittest.TestCase):
    def test_classify_row_attaches_four_fields(self) -> None:
        row = classify_row({"分组键": "SONKUKI  Pergola"})
        self.assertEqual(row["query"], "SONKUKI  Pergola")
        self.assertEqual(row["normalized_query"], "sonkuki pergola")
        self.assertEqual(row["relevance_status"], VALID)
        self.assertEqual(row["exclusion_reason"], "BRAND_PRODUCT")

    def test_clean_dataset_keeps_only_valid(self) -> None:
        rows = [classify_row({"分组键": q}) for q in ("sonkuki pergola", "randomsite.com customer service phone number", "unknown phrase")]
        clean = build_clean_dataset(rows)
        self.assertEqual([row["query"] for row in clean], ["sonkuki pergola"])


if __name__ == "__main__":
    unittest.main()
