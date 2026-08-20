#!/usr/bin/env python3
"""Deterministic normalization of reviews.theme MultiSelect values."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from nocodb_client import TABLES, NocoClient, backup_jsonl

# Canonical remaps (deterministic, no LLM)
THEME_REMAP = {
    "Durability & material": "Sturdy & durable",
    "Durable & material": "Sturdy & durable",
    "Weather & stability": "Stability & weather",
    "Comfort & cushion": "Comfort & space",
}

DROP_THEMES = {
    "Easy to use",
    "High quality",
    "Good materials",
    "Good design",
    "Good quality",
    "Works well",
    "Great product",
    "Great Features",
    "Great materials",
}


def parse_themes(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


def normalize_themes(themes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for theme in themes:
        if theme in DROP_THEMES:
            continue
        mapped = THEME_REMAP.get(theme, theme)
        if mapped and mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = args.apply

    client = NocoClient()
    rows = client.records(TABLES["reviews"], ["Id", "review_key", "theme"])
    patches = []
    remap_counter: Counter[str] = Counter()
    drop_counter: Counter[str] = Counter()

    for row in rows:
        before = parse_themes(row.get("theme"))
        after = normalize_themes(before)
        if before != after:
            for theme in before:
                if theme in DROP_THEMES:
                    drop_counter[theme] += 1
                elif theme in THEME_REMAP:
                    remap_counter[f"{theme} -> {THEME_REMAP[theme]}"] += 1
            patches.append({"Id": row["Id"], "theme": after})

    report = {
        "total_reviews": len(rows),
        "rows_to_patch": len(patches),
        "remap_counts": dict(remap_counter),
        "drop_counts": dict(drop_counter),
        "sample": patches[:3],
    }
    if patches:
        report["backup"] = str(backup_jsonl(patches, "reviews_theme_normalize"))
    if apply and patches:
        report["patched"] = client.patch_records(TABLES["reviews"], patches, batch_size=20)

    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
