#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from balance_sheet_pipeline import PipelineError, run_balance_sheet_pipeline


def main() -> int:
    try:
        run_balance_sheet_pipeline(ROOT)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print("Balance sheet vertical slice pipeline completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
