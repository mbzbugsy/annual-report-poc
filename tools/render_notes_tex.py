#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notes_provenance import NotesProvenanceError, encode_canonical_json, validate_provenance_payload  # noqa: E402
from notes_renderer import NotesRenderError, render_notes  # noqa: E402


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


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


def _cleanup_files(paths: List[Path]) -> None:
    for path in paths:
        _safe_unlink(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render deterministic notes LaTeX pages 9-19 from semantic notes contract.")
    parser.add_argument("--semantic-input", default="generated/notes.json", help="Path to semantic notes JSON contract.")
    parser.add_argument("--raw-input", default="generated/notes-workbook-raw.json", help="Path to raw notes workbook JSON contract.")
    parser.add_argument("--metadata", default="data/report_metadata.json", help="Path to report metadata JSON.")
    parser.add_argument("--mapping", default="data/notes_mapping.json", help="Path to notes mapping policy JSON.")
    parser.add_argument("--management-contract", default="generated/management-report.json", help="Path to management semantic contract JSON.")
    parser.add_argument("--override", default="data/mock/notes_preview_overrides.json", help="Path to committed notes preview override JSON.")
    parser.add_argument("--output", default="generated/notes.tex", help="Path to rendered notes LaTeX partial.")
    parser.add_argument("--provenance-output", default="generated/notes.provenance.json", help="Path to notes provenance JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    semantic_input_path = Path(args.semantic_input)
    raw_input_path = Path(args.raw_input)
    metadata_path = Path(args.metadata)
    mapping_path = Path(args.mapping)
    management_contract_path = Path(args.management_contract)
    override_path = Path(args.override)
    output_path = Path(args.output)
    provenance_output_path = Path(args.provenance_output)

    # Remove stale final artifacts before attempting a rerun.
    _safe_unlink(output_path)
    _safe_unlink(provenance_output_path)

    staged_files: List[Path] = []

    try:
        result = render_notes(
            semantic_input_path=semantic_input_path,
            raw_input_path=raw_input_path,
            metadata_path=metadata_path,
            mapping_path=mapping_path,
            management_contract_path=management_contract_path,
            preview_override_path=override_path,
        )

        tex_bytes = result["tex"].encode("utf-8")
        output_tex_sha = _sha256_bytes(tex_bytes)

        provenance_payload: Dict[str, Any] = dict(result["provenance"])
        provenance_payload["outputTexPath"] = str(output_path).replace("\\", "/")
        provenance_payload["outputTexSha256"] = output_tex_sha
        validate_provenance_payload(provenance_payload)
        provenance_bytes = encode_canonical_json(provenance_payload)

        staged_tex = _stage_bytes(output_path, tex_bytes)
        staged_provenance = _stage_bytes(provenance_output_path, provenance_bytes)
        staged_files = [staged_tex, staged_provenance]

        os.replace(staged_tex, output_path)
        os.replace(staged_provenance, provenance_output_path)
        staged_files = []
    except (NotesRenderError, NotesProvenanceError) as exc:
        _cleanup_files(staged_files)
        _safe_unlink(output_path)
        _safe_unlink(provenance_output_path)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        _cleanup_files(staged_files)
        _safe_unlink(output_path)
        _safe_unlink(provenance_output_path)
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote rendered notes partial: {output_path}")
    print(f"Wrote notes provenance: {provenance_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
