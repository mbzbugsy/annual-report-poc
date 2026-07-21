from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

SUPPORTED_PREVIOUS_PERIOD_SOURCE_CLASSIFICATIONS = {
    "synthetic_fixture",
    "real_extract",
    "manual_override",
}

EXPECTED_REAL_PARTIAL_PATH = "generated/income-statement.real.tex"
EXPECTED_REAL_PROVENANCE_PATH = "generated/income-statement.real.provenance.json"
EXPECTED_REAL_BUILD_STATUS_PATH = "generated/income-statement.real.build-status.json"
EXPECTED_PDF_PATH = "build/annual-report.pdf"
PROVENANCE_SCHEMA_VERSION = "1.1"
BUILD_STATUS_SCHEMA_VERSION = "1.0"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceValidationError(ValueError):
    pass


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_non_empty_string(provenance: Dict[str, Any], key: str) -> str:
    value = provenance.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceValidationError(f"Invalid or missing provenance field '{key}'")
    return value


def _require_run_id(run_id: str) -> str:
    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise ProvenanceValidationError("Invalid provenance runId") from exc

    canonical = str(parsed)
    if run_id != canonical:
        raise ProvenanceValidationError("Invalid provenance runId format (must be canonical lowercase UUID)")
    return canonical


def _require_sha256_hex(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ProvenanceValidationError("Invalid provenance realPartialSha256 format")
    return value


def load_provenance(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ProvenanceValidationError(f"Provenance file does not exist: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvenanceValidationError(f"Invalid real income provenance JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProvenanceValidationError("Invalid real income provenance shape")
    return raw


def validate_real_provenance(provenance: Dict[str, Any], real_partial_path: Path) -> Dict[str, str]:
    schema_version = _require_non_empty_string(provenance, "schemaVersion")
    if schema_version != PROVENANCE_SCHEMA_VERSION:
        raise ProvenanceValidationError(
            f"Unsupported provenance schemaVersion: expected {PROVENANCE_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    mode = _require_non_empty_string(provenance, "mode")
    if mode != "real":
        raise ProvenanceValidationError("Real income provenance mode must be 'real'")

    adapter_status = _require_non_empty_string(provenance, "adapterStatus")
    if adapter_status != "validated":
        raise ProvenanceValidationError("Real income provenance adapterStatus must be 'validated'")

    run_id = _require_run_id(_require_non_empty_string(provenance, "runId"))

    classification = _require_non_empty_string(provenance, "previousPeriodSourceClassification")
    if classification not in SUPPORTED_PREVIOUS_PERIOD_SOURCE_CLASSIFICATIONS:
        raise ProvenanceValidationError("Real income provenance has invalid previousPeriodSourceClassification")

    _require_non_empty_string(provenance, "previousPeriodSourceIdentifier")

    extractor_source = provenance.get("currentExtractionSource")
    if not isinstance(extractor_source, dict):
        raise ProvenanceValidationError("Real income provenance must include object currentExtractionSource")

    real_partial_rel_path = _require_non_empty_string(provenance, "realPartialPath")
    if real_partial_rel_path != EXPECTED_REAL_PARTIAL_PATH:
        raise ProvenanceValidationError("Real income provenance realPartialPath mismatch")

    expected_hash = _require_sha256_hex(_require_non_empty_string(provenance, "realPartialSha256"))

    if not real_partial_path.exists():
        raise ProvenanceValidationError(f"Real income partial is missing: {real_partial_path}")

    actual_hash = compute_file_sha256(real_partial_path)
    if actual_hash != expected_hash:
        raise ProvenanceValidationError("Real income provenance hash mismatch for real partial")

    return {
        "runId": run_id,
        "realPartialSha256": actual_hash,
        "realPartialPath": real_partial_rel_path,
        "previousPeriodSourceClassification": classification,
    }


def load_build_status(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ProvenanceValidationError(f"Real income build-status file does not exist: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProvenanceValidationError(f"Invalid real income build-status JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProvenanceValidationError("Invalid real income build-status shape")
    return raw


def validate_real_build_status(
    build_status: Dict[str, Any],
    *,
    expected_run_id: str,
    expected_real_partial_sha256: str,
) -> Dict[str, str]:
    schema_version = _require_non_empty_string(build_status, "schemaVersion")
    if schema_version != BUILD_STATUS_SCHEMA_VERSION:
        raise ProvenanceValidationError(
            f"Unsupported build-status schemaVersion: expected {BUILD_STATUS_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    status = _require_non_empty_string(build_status, "status")
    if status != "succeeded":
        raise ProvenanceValidationError("Real income build-status status must be 'succeeded'")

    mode = _require_non_empty_string(build_status, "mode")
    if mode != "real":
        raise ProvenanceValidationError("Real income build-status mode must be 'real'")

    run_id = _require_run_id(_require_non_empty_string(build_status, "runId"))
    if run_id != expected_run_id:
        raise ProvenanceValidationError("Real income build-status runId mismatch")

    pdf_path = _require_non_empty_string(build_status, "pdfPath")
    if pdf_path != EXPECTED_PDF_PATH:
        raise ProvenanceValidationError("Real income build-status pdfPath mismatch")

    provenance_path = _require_non_empty_string(build_status, "provenancePath")
    if provenance_path != EXPECTED_REAL_PROVENANCE_PATH:
        raise ProvenanceValidationError("Real income build-status provenancePath mismatch")

    status_hash = _require_sha256_hex(_require_non_empty_string(build_status, "realPartialSha256"))
    if status_hash != expected_real_partial_sha256:
        raise ProvenanceValidationError("Real income build-status realPartialSha256 mismatch")

    return {
        "runId": run_id,
        "realPartialSha256": status_hash,
    }


def _write_json_atomically(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{path.stem}-", dir=path.parent) as tmp:
        staged_path = Path(tmp) / path.name
        staged_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staged_path, path)


def write_real_build_status(
    *,
    real_partial_path: Path,
    provenance_path: Path,
    pdf_path: Path,
    output_path: Path,
) -> Dict[str, str]:
    provenance = load_provenance(provenance_path)
    validated_provenance = validate_real_provenance(provenance, real_partial_path)

    if not pdf_path.exists():
        raise ProvenanceValidationError(f"Expected PDF output is missing: {pdf_path}")

    build_status = {
        "schemaVersion": BUILD_STATUS_SCHEMA_VERSION,
        "runId": validated_provenance["runId"],
        "status": "succeeded",
        "mode": "real",
        "pdfPath": EXPECTED_PDF_PATH,
        "provenancePath": EXPECTED_REAL_PROVENANCE_PATH,
        "realPartialSha256": validated_provenance["realPartialSha256"],
    }
    _write_json_atomically(output_path, build_status)

    return {
        "runId": validated_provenance["runId"],
        "realPartialSha256": validated_provenance["realPartialSha256"],
    }
