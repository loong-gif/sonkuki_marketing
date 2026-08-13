import unittest

from sonkuki_gsc_analysis import (
    analyze,
    classify_brand,
    classify_intent,
    classify_theme,
    enrich_rows,
    normalize_page,
    normalize_query,
)


def row(date, page, query, clicks, impressions, position=10.0):
    return {
        "site_url": "sc-domain:sonkuki.com",
        "date": date,
        "page": page,
        "query": query,
        "clicks": clicks,
        "impressions": impressions,
        "ctr_source": clicks / impressions if impressions else 0.0,
        "position_source": position,
    }


class SonkukiAnalysisTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_query("  SONKUKI\u00a0Pergola  "), "sonkuki pergola")
        self.assertEqual(normalize_page("HTTP://SONKUKI.COM/a/?utm_source=x#frag"), "https://sonkuki.com/a")
        self.assertEqual(normalize_page("https://sonkuki.com"), "https://sonkuki.com/")

    def test_classification_axes(self):
        self.assertEqual(classify_brand("sonuki pergola"), "品牌")
        self.assertEqual(classify_brand("patio umbrella size for 6 person table"), "非品牌")
        self.assertEqual(classify_intent("sonkuki pergola reviews", "品牌"), "评价/信任")
        self.assertEqual(classify_intent("what size umbrella for 6 person table", "非品牌"), "信息/使用场景")
        self.assertEqual(classify_theme("LED louvered pergola", "https://sonkuki.com/collections/pergola"), "Pergola")
        self.assertEqual(classify_theme("patio umbrella base", "https://sonkuki.com/collections/outdoor-patio-umbrella-bases"), "Accessories")

    def test_weighted_metrics_and_reconciliation(self):
        rows = [
            row("2026-04-22", "https://sonkuki.com/", "sonkuki", 4, 7, 1),
            row("2026-04-23", "https://sonkuki.com/", "patio umbrella", 1, 100, 20),
        ]
        result = analyze(rows)
        self.assertEqual(result["metrics"]["total_clicks"], 5)
        self.assertEqual(result["metrics"]["total_impressions"], 107)
        self.assertAlmostEqual(result["metrics"]["overall_ctr"], 5 / 107)
        self.assertAlmostEqual(result["metrics"]["weighted_position"], (1 * 7 + 20 * 100) / 107)
        self.assertEqual(result["metrics"]["duplicate_grain_rows"], 0)

    def test_missing_dates_and_complete_week_flag(self):
        rows = [row(f"2026-04-{day:02d}", "https://sonkuki.com/", "sonkuki", 1, 10) for day in range(20, 27)]
        result = analyze(rows)
        self.assertEqual(result["profile"]["missing_dates"], [])
        self.assertTrue(any(week["complete"] for week in result["weekly"]))

    def test_opportunity_selection_is_bounded_and_actionable(self):
        rows = []
        for day in range(1, 8):
            rows.append(row(f"2026-05-{day:02d}", "https://sonkuki.com/collections/pergola", "louvered pergola", 0, 50, 6))
        rows.append(row("2026-05-08", "https://sonkuki.com/collections/pergola?variant=1", "louvered pergola", 0, 50, 6))
        result = analyze(rows)
        self.assertGreaterEqual(len(result["opportunities"]), 1)
        self.assertIn("action", result["opportunities"][0])
        self.assertLessEqual(len(result["opportunities"]), 25)

    def test_obvious_non_target_queries_are_isolated_from_market_dimensions(self):
        rows = [
            row("2026-05-01", "https://sonkuki.com/", "sonkuki pergola", 4, 40, 3),
            row("2026-05-01", "https://sonkuki.com/", "example.com customer service phone number", 6, 60, 8),
        ]
        result = analyze(rows)
        self.assertEqual(result["metrics"]["total_clicks"], 10)
        self.assertEqual(result["metrics"]["suspicious_query_clicks"], 6)
        self.assertEqual(sum(item["clicks"] for item in result["intent_mix"]), 4)
        self.assertTrue(all("example.com" not in item["normalized_query"] for item in result["opportunities"]))


if __name__ == "__main__":
    unittest.main()
