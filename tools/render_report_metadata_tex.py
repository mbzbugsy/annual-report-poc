#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from report_metadata import load_report_metadata


def escape_latex(text: str) -> str:
    replacements = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "_": "\\_",
        "#": "\\#",
        "$": "\\$",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _oneline(value: str) -> str:
    return " \\\\ ".join(escape_latex(part.strip()) for part in value.splitlines() if part.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render centralized report metadata as a LaTeX partial.")
    parser.add_argument(
        "--input",
        default="data/report_metadata.json",
        help="Path to report metadata JSON",
    )
    parser.add_argument(
        "--output",
        default="generated/report-metadata.tex",
        help="Path to output TeX partial",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    metadata = load_report_metadata(input_path)

    tex = "\n".join(
        [
            "% AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.",
            f"\\newcommand{{\\reporttitle}}{{{escape_latex(metadata.report_title)}}}",
            f"\\newcommand{{\\companyname}}{{{escape_latex(metadata.company_name)}}}",
            f"\\newcommand{{\\organizationnumber}}{{{escape_latex(metadata.organization_number)}}}",
            f"\\newcommand{{\\reportsubtitle}}{{{escape_latex(metadata.report_subtitle)}}}",
            f"\\newcommand{{\\reportcity}}{{{escape_latex(metadata.city)}}}",
            f"\\newcommand{{\\fiscalyear}}{{{escape_latex(metadata.fiscal_year)}}}",
            f"\\newcommand{{\\documentyear}}{{{escape_latex(metadata.document_year)}}}",
            f"\\newcommand{{\\currentreportingperiod}}{{{_oneline(metadata.current_reporting_period)}}}",
            f"\\newcommand{{\\previousreportingperiod}}{{{_oneline(metadata.previous_reporting_period)}}}",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tex, encoding="utf-8")
    print(f"Wrote report metadata partial: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
