#!/usr/bin/env python3
"""Build requests not present in a prior follow-up dataset output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_residual_requests(all_input: Path, prior_output: Path) -> list[dict]:
    requests = json.loads(all_input.read_text(encoding="utf-8"))["input"]
    records = json.loads(prior_output.read_text(encoding="utf-8"))
    completed_pages = {
        (record.get("itemId"), record.get("currentPage"))
        for record in records
        if record.get("itemId") and record.get("currentPage")
    }
    return [
        request
        for request in requests
        if (request["itemId"], request["startPage"]) not in completed_pages
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("all_input", type=Path)
    parser.add_argument("prior_output", type=Path)
    parser.add_argument("residual_output", type=Path)
    args = parser.parse_args()

    requests = build_residual_requests(args.all_input, args.prior_output)
    args.residual_output.write_text(
        json.dumps({"input": requests}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"residual_requests={len(requests)}")
    print(f"output={args.residual_output}")


if __name__ == "__main__":
    main()
