#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from balance_sheet_extractor import ExtractionError, extract_balance_sheet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract deterministic real balance-sheet values from BR Sammanställning and Eget kapital."
    )
    parser.add_argument(
        "--input",
        default="source-data/Resultaträkning, balansräkning,eget kapital etc.xlsx",
        help="Path to source workbook (.xlsx)",
    )
    parser.add_argument(
        "--output",
        default="generated/balance-sheet-extraction.json",
        help="Path to output JSON file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook = Path(args.input)
    output = Path(args.output)

    try:
        payload = extract_balance_sheet(workbook, output)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote extracted balance sheet JSON: {output}")
    print(f"Extraction status: {payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
