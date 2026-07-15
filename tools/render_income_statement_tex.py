#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_renderer import RenderError, render_income_statement_tex


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render income statement LaTeX from generated income-statement JSON."
    )
    parser.add_argument(
        "--input",
        default="generated/income-statement.json",
        help="Path to input JSON",
    )
    parser.add_argument(
        "--output",
        default="generated/income-statement.tex",
        help="Path to output LaTeX partial",
    )
    parser.add_argument(
        "--previous-period-fixture",
        default="data/mock/income_statement_previous_period_fixture.json",
        help="Path to non-production previous-period fixture used for visual comparison",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    previous_period_fixture_path = Path(args.previous_period_fixture)

    try:
        render_income_statement_tex(
            input_path,
            output_path,
            previous_period_fixture_path=previous_period_fixture_path,
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
