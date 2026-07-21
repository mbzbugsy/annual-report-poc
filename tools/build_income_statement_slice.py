#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_provenance import SUPPORTED_PREVIOUS_PERIOD_SOURCE_CLASSIFICATIONS
from income_statement_pipeline import PipelineError, run_income_statement_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real income-statement extract -> adapt/validate -> render -> build pipeline."
    )
    parser.add_argument(
        "--previous-period-source",
        required=True,
        help="Explicit previous-period source JSON path (no implicit fallback).",
    )
    parser.add_argument(
        "--previous-period-source-type",
        required=True,
        choices=sorted(SUPPORTED_PREVIOUS_PERIOD_SOURCE_CLASSIFICATIONS),
        help="Explicit previous-period source classification for adapter provenance.",
    )
    parser.add_argument(
        "--metadata",
        default="data/report_metadata.json",
        help="Path to report metadata JSON.",
    )
    parser.add_argument(
        "--input",
        default="source-data/Resultaträkning, balansräkning,eget kapital etc.xlsx",
        help="Path to current-period source workbook.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.previous_period_source_type == "synthetic_fixture":
        print(
            "WARNING: previous-period source classification is synthetic_fixture; "
            "result is not a fully real two-period report.",
            file=sys.stderr,
        )
    try:
        run_income_statement_pipeline(
            ROOT,
            previous_period_source_path=Path(args.previous_period_source),
            previous_period_source_type=args.previous_period_source_type,
            metadata_path=Path(args.metadata),
            workbook_path=Path(args.input),
        )
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print("Income statement vertical slice pipeline completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
