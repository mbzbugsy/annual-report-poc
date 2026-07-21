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
    load_provenance,
    validate_real_provenance,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate generated income-statement real-mode provenance against the real partial bytes."
    )
    parser.add_argument("--real-partial", required=True, help="Path to generated real income-statement TeX partial")
    parser.add_argument("--provenance", required=True, help="Path to real-mode provenance JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    real_partial = Path(args.real_partial)
    provenance_path = Path(args.provenance)

    try:
        provenance = load_provenance(provenance_path)
        validate_real_provenance(provenance, real_partial)
    except ProvenanceValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
