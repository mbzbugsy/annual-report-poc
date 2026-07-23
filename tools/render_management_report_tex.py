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

from management_report_provenance import (  # noqa: E402
    ManagementReportProvenanceError,
    encode_canonical_json,
)
from management_report_renderer import (  # noqa: E402
    ManagementReportRenderError,
    render_management_report,
)


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
    parser = argparse.ArgumentParser(
        description="Render management-report LaTeX pages 2-4 from semantic contract JSON."
    )
    parser.add_argument(
        "--semantic-input",
        default="generated/management-report.json",
        help="Path to semantic management-report JSON contract.",
    )
    parser.add_argument(
        "--raw-input",
        default="generated/management-report-raw.json",
        help="Path to raw management-report JSON contract.",
    )
    parser.add_argument(
        "--metadata",
        default="data/report_metadata.json",
        help="Path to report metadata JSON.",
    )
    parser.add_argument(
        "--output",
        default="generated/management-report.tex",
        help="Path to rendered management-report LaTeX partial.",
    )
    parser.add_argument(
        "--override",
        default="data/mock/management_report_page4_preview_override.json",
        help="Path to committed page-4 preview override JSON.",
    )
    parser.add_argument(
        "--provenance-output",
        default="generated/management-report.provenance.json",
        help="Path to management-report provenance JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    semantic_input_path = Path(args.semantic_input)
    raw_input_path = Path(args.raw_input)
    metadata_path = Path(args.metadata)
    output_path = Path(args.output)
    override_path = Path(args.override)
    provenance_output_path = Path(args.provenance_output)

    # Prevent stale successful artifacts from being reused after a failed rerun.
    _safe_unlink(output_path)
    _safe_unlink(provenance_output_path)

    staged_files: List[Path] = []

    try:
        result = render_management_report(
            semantic_input_path=semantic_input_path,
            raw_input_path=raw_input_path,
            metadata_path=metadata_path,
            preview_override_path=override_path,
        )

        tex_bytes = result["tex"].encode("utf-8")
        output_tex_sha = _sha256_bytes(tex_bytes)

        provenance_payload: Dict[str, Any] = dict(result["provenance"])
        provenance_payload["outputTexPath"] = str(output_path).replace("\\", "/")
        provenance_payload["outputTexSha256"] = output_tex_sha
        provenance_bytes = encode_canonical_json(provenance_payload)

        staged_tex = _stage_bytes(output_path, tex_bytes)
        staged_provenance = _stage_bytes(provenance_output_path, provenance_bytes)
        staged_files = [staged_tex, staged_provenance]

        os.replace(staged_tex, output_path)
        os.replace(staged_provenance, provenance_output_path)
        staged_files = []
    except (ManagementReportRenderError, ManagementReportProvenanceError) as exc:
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

    print(f"Wrote rendered management-report partial: {output_path}")
    print(f"Wrote management-report provenance: {provenance_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
