#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_provenance import (  # noqa: E402
    ProvenanceValidationError,
    write_real_build_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write real-mode build-status after successful PDF build using validated provenance/hash."
    )
    parser.add_argument("--real-partial", required=True, help="Path to generated real income-statement TeX partial")
    parser.add_argument("--provenance", required=True, help="Path to real-mode provenance JSON")
    parser.add_argument("--pdf", required=True, help="Path to built annual-report PDF")
    parser.add_argument("--output", required=True, help="Path to write build-status JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        write_real_build_status(
            real_partial_path=Path(args.real_partial),
            provenance_path=Path(args.provenance),
            pdf_path=Path(args.pdf),
            output_path=Path(args.output),
        )
    except ProvenanceValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
