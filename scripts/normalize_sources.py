#!/usr/bin/env python3
"""Normalize security blog source CSVs into a clean grouped table or JSON."""

from __future__ import annotations

import argparse
import csv
import json
from collections import OrderedDict
from pathlib import Path


def read_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        last_category = ""
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                row = {str(key).strip(): (value or "").strip() for key, value in raw.items()}
                if not any(row.values()):
                    continue
                category = row.get("Category", "")
                if category:
                    last_category = category
                elif last_category:
                    row["Category"] = last_category
                rows.append(row)
    return rows


def dedupe(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        key = (
            row.get("Category", "").lower(),
            row.get("Platform", "").lower(),
            row.get("Portal", "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def group_rows(rows: list[dict[str, str]]) -> "OrderedDict[str, list[dict[str, str]]]":
    grouped: "OrderedDict[str, list[dict[str, str]]]" = OrderedDict()
    for row in rows:
        category = row.get("Category", "").strip() or "Uncategorized"
        grouped.setdefault(category, []).append(row)
    return grouped


def markdown_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(rows: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for category, items in group_rows(rows).items():
        parts.append(f"## {category}")
        parts.append("")
        parts.append("| Platform | Portal | Notes |")
        parts.append("|---|---|---|")
        for row in items:
            parts.append(
                "| "
                + " | ".join(
                    [
                        markdown_escape(row.get("Platform", "")),
                        markdown_escape(row.get("Portal", "")),
                        markdown_escape(row.get("Notes", "")),
                    ]
                )
                + " |"
            )
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True, type=Path, help="CSV file to normalize")
    parser.add_argument("--output", type=Path, help="Write output to a file instead of stdout")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--no-dedupe", action="store_true", help="Keep duplicate rows")
    args = parser.parse_args()

    rows = read_rows(args.input)
    if not args.no_dedupe:
        rows = dedupe(rows)

    if args.format == "json":
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
    else:
        payload = render_markdown(rows)

    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
