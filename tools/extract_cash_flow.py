#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cash_flow_extractor import ExtractionError, extract_cash_flow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract cash-flow lines from KFA/ÅR Layout into normalized JSON with traceability metadata."
    )
    parser.add_argument(
        "--input",
        default="source-data/Kassaflödesanalys 2025 - Omegapoint Malmö.xlsx",
        help="Path to source workbook (.xlsx)",
    )
    parser.add_argument(
        "--output",
        default="generated/cash-flow-extraction.json",
        help="Path to output JSON file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook = Path(args.input)
    output = Path(args.output)

    try:
        extract_cash_flow(workbook, output)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote extracted cash-flow JSON: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
