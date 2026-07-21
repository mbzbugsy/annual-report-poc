from __future__ import annotations

import copy
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from income_statement_provenance import SUPPORTED_PREVIOUS_PERIOD_SOURCE_CLASSIFICATIONS
from income_statement_renderer import LAYOUT_ROWS, REQUIRED_CURRENT_KEYS
from report_metadata import ReportMetadata


class IncomeStatementAdapterError(Exception):
    pass


ALLOWED_PREVIOUS_PERIOD_SOURCE_TYPES = set(SUPPORTED_PREVIOUS_PERIOD_SOURCE_CLASSIFICATIONS)


def load_previous_period_source(path: Path) -> Dict[str, object]:
    if not path.exists():
        raise IncomeStatementAdapterError(f"Previous-period source does not exist: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IncomeStatementAdapterError(f"Invalid previous-period source JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise IncomeStatementAdapterError("Previous-period source JSON must be an object")

    values = raw.get("values")
    if not isinstance(values, dict):
        raise IncomeStatementAdapterError("Previous-period source must contain object field 'values'")

    return raw


def validate_previous_period_source_type(source_type: str) -> None:
    if source_type not in ALLOWED_PREVIOUS_PERIOD_SOURCE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_PREVIOUS_PERIOD_SOURCE_TYPES))
        raise IncomeStatementAdapterError(
            f"Unsupported previous-period source type: {source_type!r}. Allowed values: {allowed}"
        )


def _normalize_period_label(value: str) -> str:
    return "\n".join(part.strip() for part in value.splitlines() if part.strip())


def _parse_decimal_or_fail(label: str, value: object) -> Decimal:
    if not isinstance(value, str):
        raise IncomeStatementAdapterError(
            f"Invalid value type for '{label}': expected string, got {type(value).__name__}"
        )
    if not value.strip():
        raise IncomeStatementAdapterError(f"Invalid value for '{label}': empty string")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise IncomeStatementAdapterError(f"Invalid decimal value for '{label}': {value!r}") from exc


def _renderer_optional_keys() -> Set[str]:
    keys: Set[str] = set()
    for row in LAYOUT_ROWS:
        if row.kind == "line" and row.key:
            keys.add(row.key)
    return keys.difference(REQUIRED_CURRENT_KEYS)


def _validate_current_lines(lines: Dict[str, object]) -> Tuple[Dict[str, Dict[str, str]], Dict[str, object]]:
    renderer_line_keys: Set[str] = set(REQUIRED_CURRENT_KEYS).union(_renderer_optional_keys())

    required_passed: List[str] = []
    optional_passed: List[str] = []
    optional_missing: List[str] = []

    adapted_lines: Dict[str, Dict[str, str]] = {}

    for key in REQUIRED_CURRENT_KEYS:
        entry = lines.get(key)
        if not isinstance(entry, dict):
            raise IncomeStatementAdapterError(f"Missing required line object: {key}")
        raw_value = entry.get("value")
        if raw_value is None:
            raise IncomeStatementAdapterError(f"Required line value is null: {key}")
        _parse_decimal_or_fail(key, raw_value)
        adapted_lines[key] = {"value": raw_value}
        required_passed.append(key)

    for key in sorted(_renderer_optional_keys()):
        if key not in lines:
            optional_missing.append(key)
            continue
        entry = lines.get(key)
        if not isinstance(entry, dict):
            raise IncomeStatementAdapterError(f"Optional line object is invalid: {key}")
        raw_value = entry.get("value")
        if raw_value is None:
            raise IncomeStatementAdapterError(f"Optional line value is null: {key}")
        _parse_decimal_or_fail(key, raw_value)
        adapted_lines[key] = {"value": raw_value}
        optional_passed.append(key)

    extra_lines = sorted(k for k in lines.keys() if k not in renderer_line_keys)

    audit = {
        "required": {
            "validated": required_passed,
            "count": len(required_passed),
        },
        "optional": {
            "validated": optional_passed,
            "missing": optional_missing,
        },
        "extraExtractorLines": extra_lines,
    }
    return adapted_lines, audit


def _validate_previous_values(previous_values: Dict[str, object]) -> Tuple[Dict[str, str], Dict[str, object]]:
    adapted_values: Dict[str, str] = {}

    required_passed: List[str] = []
    optional_passed: List[str] = []
    optional_missing: List[str] = []

    for key in REQUIRED_CURRENT_KEYS:
        raw_value = previous_values.get(key)
        if raw_value is None:
            raise IncomeStatementAdapterError(f"Previous-period required value is missing: {key}")
        _parse_decimal_or_fail(f"previous.{key}", raw_value)
        adapted_values[key] = raw_value
        required_passed.append(key)

    for key in sorted(_renderer_optional_keys()):
        if key not in previous_values:
            optional_missing.append(key)
            continue
        raw_value = previous_values.get(key)
        if raw_value is None:
            raise IncomeStatementAdapterError(f"Previous-period optional value is null: {key}")
        _parse_decimal_or_fail(f"previous.{key}", raw_value)
        adapted_values[key] = raw_value
        optional_passed.append(key)

    audit = {
        "required": {
            "validated": required_passed,
            "count": len(required_passed),
        },
        "optional": {
            "validated": optional_passed,
            "missing": optional_missing,
        },
    }
    return adapted_values, audit


def adapt_income_statement_for_renderer(
    extraction_payload: Dict[str, object],
    metadata: ReportMetadata,
    previous_period_source_payload: Dict[str, object],
    *,
    previous_period_source_type: str,
    previous_period_source_identifier: str,
) -> Dict[str, object]:
    validate_previous_period_source_type(previous_period_source_type)

    status_value = extraction_payload.get("status")
    status_present = "status" in extraction_payload
    if status_present and status_value != "ok":
        raise IncomeStatementAdapterError(
            "Income extraction payload status is not renderable: "
            f"expected 'ok', got {status_value!r}"
        )

    lines = extraction_payload.get("lines")
    if not isinstance(lines, dict):
        raise IncomeStatementAdapterError("Extraction payload is missing 'lines' object")

    if not metadata.current_reporting_period.strip():
        raise IncomeStatementAdapterError("Metadata currentReportingPeriod is missing")
    if not metadata.previous_reporting_period.strip():
        raise IncomeStatementAdapterError("Metadata previousReportingPeriod is missing")

    adapted_current_lines, current_validation_audit = _validate_current_lines(lines)

    previous_values_raw = previous_period_source_payload.get("values")
    if not isinstance(previous_values_raw, dict):
        raise IncomeStatementAdapterError("Previous-period source must contain object field 'values'")
    adapted_previous_values, previous_validation_audit = _validate_previous_values(previous_values_raw)

    extractor_period = extraction_payload.get("period")
    extractor_reporting_period: Optional[str] = None
    extractor_period_validated = False
    extractor_period_evidence_available = False

    if isinstance(extractor_period, dict):
        candidate = extractor_period.get("reportingPeriod")
        if isinstance(candidate, str) and candidate.strip():
            extractor_period_evidence_available = True
            extractor_reporting_period = candidate
            if _normalize_period_label(candidate) != _normalize_period_label(metadata.current_reporting_period):
                raise IncomeStatementAdapterError(
                    "Extractor current period contradicts metadata currentReportingPeriod"
                )
            extractor_period_validated = True

    previous_source_period = previous_period_source_payload.get("periodLabel")
    previous_source_period_validated = False
    previous_source_period_available = False

    if isinstance(previous_source_period, str) and previous_source_period.strip():
        previous_source_period_available = True
        if _normalize_period_label(previous_source_period) != _normalize_period_label(metadata.previous_reporting_period):
            raise IncomeStatementAdapterError(
                "Previous-period source label contradicts metadata previousReportingPeriod"
            )
        previous_source_period_validated = True

    current_payload = {
        "schemaVersion": "1.0",
        "source": copy.deepcopy(extraction_payload.get("source")),
        "lines": adapted_current_lines,
    }

    previous_payload = {
        "fixtureType": "adapter-validated-previous-period-source",
        "periodLabel": metadata.previous_reporting_period,
        "values": adapted_previous_values,
    }

    audit = {
        "adapterVersion": "1.0",
        "adapterStatus": "validated",
        "statusPolicy": {
            "statusPresent": status_present,
            "statusValue": status_value,
            "accepted": not status_present or status_value == "ok",
        },
        "sources": {
            "extractor": copy.deepcopy(extraction_payload.get("source")),
            "previousPeriodSource": {
                "classification": previous_period_source_type,
                "identifier": previous_period_source_identifier,
                "isSyntheticComparisonSource": previous_period_source_type == "synthetic_fixture",
            },
        },
        "metadata": {
            "currentReportingPeriod": metadata.current_reporting_period,
            "previousReportingPeriod": metadata.previous_reporting_period,
        },
        "lineValidation": {
            "current": current_validation_audit,
            "previous": previous_validation_audit,
        },
        "periodValidation": {
            "extractorEvidenceAvailable": extractor_period_evidence_available,
            "extractorReportingPeriod": extractor_reporting_period,
            "extractorEvidenceValidated": extractor_period_validated,
            "previousSourcePeriodAvailable": previous_source_period_available,
            "previousSourcePeriodLabel": previous_source_period,
            "previousSourcePeriodValidated": previous_source_period_validated,
        },
        "presentationPeriods": {
            "current": metadata.current_reporting_period,
            "previous": metadata.previous_reporting_period,
        },
        "originalExtractionPayload": copy.deepcopy(extraction_payload),
    }

    return {
        "rendererCurrentPayload": current_payload,
        "rendererPreviousPayload": previous_payload,
        "currentReportingPeriodLabel": metadata.current_reporting_period,
        "previousReportingPeriodLabel": metadata.previous_reporting_period,
        "audit": audit,
    }
