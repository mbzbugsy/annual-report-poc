#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from management_report_contract import (  # noqa: E402
    ContractError,
    build_semantic_management_report_contract,
    semantic_contract_json_bytes,
)
from management_report_docx_extractor import (  # noqa: E402
    ExtractionError,
    extract_management_report_raw,
    raw_contract_json_bytes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract deterministic raw and semantic management-report contracts from DOCX source."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to source management-report DOCX",
    )
    parser.add_argument(
        "--metadata",
        required=True,
        help="Path to report metadata JSON",
    )
    parser.add_argument(
        "--raw-output",
        required=True,
        help="Path to output raw contract JSON",
    )
    parser.add_argument(
        "--semantic-output",
        required=True,
        help="Path to output semantic contract JSON",
    )
    return parser.parse_args()


def _stage_payload(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        return Path(tmp_name)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _promote_staged(staged_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_path, final_path)


def _cleanup_staged(paths: List[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    metadata_path = Path(args.metadata)
    raw_output = Path(args.raw_output)
    semantic_output = Path(args.semantic_output)

    staged_files: List[Path] = []
    try:
        raw_contract = extract_management_report_raw(input_path)
        raw_bytes = raw_contract_json_bytes(raw_contract)
        staged_raw = _stage_payload(raw_output, raw_bytes)
        staged_files.append(staged_raw)

        semantic_contract = build_semantic_management_report_contract(raw_contract, metadata_path)
        semantic_bytes = semantic_contract_json_bytes(semantic_contract)
        staged_semantic = _stage_payload(semantic_output, semantic_bytes)
        staged_files.append(staged_semantic)

        # Promotion is ordered raw -> semantic. If interrupted mid-promotion,
        # semantic.rawContractSha256 allows consumers to detect mismatch.
        _promote_staged(staged_raw, raw_output)
        _promote_staged(staged_semantic, semantic_output)
        staged_files = []
    except (ExtractionError, ContractError, ValueError) as exc:
        _cleanup_staged(staged_files)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        _cleanup_staged(staged_files)
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote raw contract: {raw_output}")
    print(f"Wrote semantic contract: {semantic_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
