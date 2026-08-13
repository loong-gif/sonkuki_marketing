"""Build bounded analysis outputs and the canonical Data Analytics report artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from sonkuki_gsc_analysis import analyze, build_artifact, load_rows, save_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/Users/wyl/Downloads/sonkuki_gsc_export - SCD_Raw.csv")
    parser.add_argument("--output-dir", default="outputs/sonkuki_gsc_analysis")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = analyze(load_rows(args.input))
    artifact = build_artifact(analysis)
    summary = {key: value for key, value in analysis.items() if key != "rows"}
    save_json(output_dir / "analysis_summary.json", summary)
    save_json(output_dir / "artifact.json", artifact)
    (output_dir / "source_notes.md").write_text(
        "# Sonkuki GSC analysis\n\n"
        f"Source: `{analysis['source_file']}`\n\n"
        f"Data window: {analysis['profile']['date_min']} to {analysis['profile']['date_max']}\n\n"
        "Database enrichment was intentionally skipped unless a secure HTTPS/tunnel endpoint is available.\n",
        encoding="utf-8",
    )
    print({"artifact": str(output_dir / "artifact.json"), "rows": analysis["metrics"]["row_count"], "clicks": analysis["metrics"]["total_clicks"], "impressions": analysis["metrics"]["total_impressions"]})


if __name__ == "__main__":
    main()

