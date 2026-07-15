#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_extractor import ExtractionError, extract_income_statement


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract selected income statement lines from RR sammanställning into normalized JSON."
    )
    parser.add_argument(
        "--input",
        default="source-data/Resultaträkning, balansräkning,eget kapital etc.xlsx",
        help="Path to source workbook (.xlsx)",
    )
    parser.add_argument(
        "--output",
        default="generated/income-statement.json",
        help="Path to output JSON file",
    )
    parser.add_argument(
        "--sheet",
        help="Optional sheet name override. If omitted, profile default is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook = Path(args.input)
    output = Path(args.output)

    try:
        extract_income_statement(workbook, output, sheet_name=args.sheet)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote extracted income statement JSON: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
