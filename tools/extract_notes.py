#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notes_contract import (  # noqa: E402
    NotesContractError,
    build_semantic_notes_contract,
    semantic_notes_contract_json_bytes,
)
from notes_workbook_extractor import (  # noqa: E402
    NotesWorkbookExtractionError,
    extract_notes_workbook_raw,
    raw_notes_workbook_contract_json_bytes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract deterministic notes workbook raw + semantic contracts from Not uppgifterna.xlsx."
    )
    parser.add_argument("--input", required=True, help="Path to source notes workbook (.xlsx)")
    parser.add_argument("--metadata", required=True, help="Path to report metadata JSON")
    parser.add_argument("--mapping", required=True, help="Path to notes mapping policy JSON")
    parser.add_argument(
        "--management-contract",
        help="Optional path to management semantic contract (used only for excluded post-report note-update content)",
    )
    parser.add_argument("--raw-output", required=True, help="Path to output raw workbook contract JSON")
    parser.add_argument("--semantic-output", required=True, help="Path to output semantic notes contract JSON")
    return parser.parse_args()


def _stage_bytes(path: Path, payload: bytes) -> Path:
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


def _cleanup(paths: List[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def main() -> int:
    args = parse_args()

    workbook_path = Path(args.input)
    metadata_path = Path(args.metadata)
    mapping_path = Path(args.mapping)
    management_path: Optional[Path] = Path(args.management_contract) if args.management_contract else None
    raw_output = Path(args.raw_output)
    semantic_output = Path(args.semantic_output)

    staged_files: List[Path] = []

    try:
        raw_contract = extract_notes_workbook_raw(workbook_path, mapping_path)
        raw_bytes = raw_notes_workbook_contract_json_bytes(raw_contract)
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        semantic_contract = build_semantic_notes_contract(
            raw_contract=raw_contract,
            mapping_path=mapping_path,
            metadata_path=metadata_path,
            management_contract_path=management_path,
            expected_raw_contract_sha256=raw_hash,
        )

        semantic_bytes = semantic_notes_contract_json_bytes(semantic_contract)

        staged_raw = _stage_bytes(raw_output, raw_bytes)
        staged_semantic = _stage_bytes(semantic_output, semantic_bytes)
        staged_files = [staged_raw, staged_semantic]

        os.replace(staged_raw, raw_output)
        os.replace(staged_semantic, semantic_output)
        staged_files = []
    except (NotesWorkbookExtractionError, NotesContractError, ValueError) as exc:
        _cleanup(staged_files)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        _cleanup(staged_files)
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    # Ensure no stale staging files remain beside outputs.
    _safe_unlink(raw_output.parent / f".{raw_output.name}.tmp")
    _safe_unlink(semantic_output.parent / f".{semantic_output.name}.tmp")

    print(f"Wrote raw notes workbook contract: {raw_output}")
    print(f"Wrote semantic notes contract: {semantic_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())