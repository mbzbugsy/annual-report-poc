#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cash_flow_renderer import RenderError, render_cash_flow_tex


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render synthetic cash-flow LaTeX from normalized cash-flow JSON fixture."
    )
    parser.add_argument(
        "--input",
        default="data/mock/cash_flow_fixture.json",
        help="Path to synthetic cash-flow fixture JSON",
    )
    parser.add_argument(
        "--output",
        default="generated/cash-flow.tex",
        help="Path to output LaTeX partial",
    )
    parser.add_argument(
        "--metadata",
        default="data/report_metadata.json",
        help="Path to report metadata JSON used for period-label validation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    metadata_path = Path(args.metadata)

    try:
        render_cash_flow_tex(
            input_path,
            output_path,
            metadata_path=metadata_path,
        )
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote rendered LaTeX partial: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
