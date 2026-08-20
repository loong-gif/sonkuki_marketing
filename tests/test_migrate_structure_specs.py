"""Tests for migrate_structure_specs helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from migrate_structure_specs import item_id_from_listing_key, numeric  # noqa: E402


class MigrateStructureSpecsTests(unittest.TestCase):
    def test_item_id_from_listing_key(self) -> None:
        self.assertEqual(item_id_from_listing_key("HOME_DEPOT:333087256"), "333087256")
        self.assertEqual(item_id_from_listing_key("https://www.homedepot.com/p/333087256"), "333087256")
        self.assertIsNone(item_id_from_listing_key(""))

    def test_numeric_rejects_invalid(self) -> None:
        self.assertEqual(numeric("12.5"), 12.5)
        self.assertIsNone(numeric("0"))
        self.assertIsNone(numeric("n/a"))


if __name__ == "__main__":
    unittest.main()
