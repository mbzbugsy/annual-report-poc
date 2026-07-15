from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReportMetadata:
    company_name: str
    organization_number: str
    report_title: str
    report_subtitle: str
    current_reporting_period: str
    previous_reporting_period: str
    city: str
    report_year: str


REQUIRED_METADATA_FIELDS = {
    "companyName",
    "organizationNumber",
    "reportTitle",
    "reportSubtitle",
    "currentReportingPeriod",
    "previousReportingPeriod",
    "city",
    "reportYear",
}


def default_metadata_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "report_metadata.json"


def load_report_metadata(metadata_path: Path | None = None) -> ReportMetadata:
    path = metadata_path or default_metadata_path()
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError("Report metadata JSON must be an object")

    missing = sorted(REQUIRED_METADATA_FIELDS.difference(raw.keys()))
    if missing:
        raise ValueError(f"Missing required report metadata fields: {missing}")

    def _require_non_empty_string(field_name: str) -> str:
        value = raw[field_name]
        if not isinstance(value, str):
            raise ValueError(
                f"Invalid report metadata field '{field_name}': expected non-empty string, got {type(value).__name__}"
            )

        if not value.strip():
            raise ValueError(
                f"Invalid report metadata field '{field_name}': value must be a non-empty string"
            )

        return value

    return ReportMetadata(
        company_name=_require_non_empty_string("companyName"),
        organization_number=_require_non_empty_string("organizationNumber"),
        report_title=_require_non_empty_string("reportTitle"),
        report_subtitle=_require_non_empty_string("reportSubtitle"),
        current_reporting_period=_require_non_empty_string("currentReportingPeriod"),
        previous_reporting_period=_require_non_empty_string("previousReportingPeriod"),
        city=_require_non_empty_string("city"),
        report_year=_require_non_empty_string("reportYear"),
    )
