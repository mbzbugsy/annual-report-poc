from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_adapter import (  # noqa: E402
    ALLOWED_PREVIOUS_PERIOD_SOURCE_TYPES,
    IncomeStatementAdapterError,
    adapt_income_statement_for_renderer,
    load_previous_period_source,
)
from income_statement_renderer import render_income_statement_tex  # noqa: E402
from report_metadata import ReportMetadata  # noqa: E402


REQUIRED_CURRENT_KEYS = [
    "revenue",
    "otherOperatingIncome",
    "totalIncome",
    "operatingResult",
    "resultAfterFinancialItems",
    "profitBeforeTax",
    "taxForYear",
    "netResult",
]

OPTIONAL_KEYS = [
    "costOfGoodsAndServices",
    "otherExternalCosts",
    "personnelCosts",
    "depreciationAndAmortization",
    "otherOperatingCosts",
    "totalOperatingCosts",
    "interestIncome",
    "interestCosts",
    "netFinancialItems",
    "appropriations",
]


def _metadata() -> ReportMetadata:
    return ReportMetadata(
        company_name="Example AB",
        organization_number="556000-0000",
        report_title="Årsredovisning 2025",
        report_subtitle="PoC",
        current_reporting_period="2025-01-01\n-2025-12-31",
        previous_reporting_period="2024-01-01\n-2024-12-31",
        city="Göteborg",
        fiscal_year="2025",
        document_year="2026",
    )


def _extraction_lines(valid: bool = True) -> dict[str, dict[str, object]]:
    lines: dict[str, dict[str, object]] = {}
    for idx, key in enumerate(REQUIRED_CURRENT_KEYS, start=1):
        lines[key] = {"value": str(1000 + idx)}
    for idx, key in enumerate(OPTIONAL_KEYS, start=1):
        if valid:
            lines[key] = {"value": str(2000 + idx)}
    return lines


def _extraction_payload(*, with_status: bool = False, status: str = "ok", period: object = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "1.0",
        "source": {"file": "source-data/file.xlsx", "sheet": "RR sammanställning"},
        "lines": _extraction_lines(),
        "period": {"reportingPeriod": period, "source": None, "note": "test"},
    }
    if with_status:
        payload["status"] = status
    return payload


def _previous_source(*, include_period: bool = True, period_label: str = "2024-01-01\n-2024-12-31") -> dict[str, object]:
    values: dict[str, object] = {}
    for idx, key in enumerate(REQUIRED_CURRENT_KEYS, start=1):
        values[key] = str(3000 + idx)
    for idx, key in enumerate(OPTIONAL_KEYS, start=1):
        values[key] = str(4000 + idx)

    payload: dict[str, object] = {
        "fixtureType": "explicit-test-source",
        "values": values,
    }
    if include_period:
        payload["periodLabel"] = period_label
    return payload


class IncomeStatementAdapterTests(unittest.TestCase):
    def test_valid_real_extraction_accepted(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="data/mock/prev.json",
        )
        self.assertIn("rendererCurrentPayload", adapted)
        self.assertIn("rendererPreviousPayload", adapted)
        self.assertIn("audit", adapted)

    def test_renderer_ready_values_remain_identical_to_extractor_values(self) -> None:
        extraction = _extraction_payload()
        adapted = adapt_income_statement_for_renderer(
            extraction,
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="data/mock/prev.json",
        )
        for key in REQUIRED_CURRENT_KEYS:
            self.assertEqual(
                adapted["rendererCurrentPayload"]["lines"][key]["value"],
                extraction["lines"][key]["value"],
            )

    def test_missing_required_line_rejected(self) -> None:
        extraction = _extraction_payload()
        extraction["lines"].pop("revenue")
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                extraction,
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_null_required_value_rejected(self) -> None:
        extraction = _extraction_payload()
        extraction["lines"]["revenue"]["value"] = None
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                extraction,
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_non_numeric_required_value_rejected(self) -> None:
        extraction = _extraction_payload()
        extraction["lines"]["revenue"]["value"] = "N/A"
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                extraction,
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_optional_absent_line_accepted(self) -> None:
        extraction = _extraction_payload()
        extraction["lines"].pop("interestIncome")
        adapted = adapt_income_statement_for_renderer(
            extraction,
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="id",
        )
        self.assertNotIn("interestIncome", adapted["rendererCurrentPayload"]["lines"])

    def test_optional_invalid_line_rejected(self) -> None:
        extraction = _extraction_payload()
        extraction["lines"]["interestIncome"]["value"] = "bad"
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                extraction,
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_payload_status_review_required_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(with_status=True, status="review_required"),
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_payload_status_null_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(with_status=True, status=None),
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_payload_status_empty_string_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(with_status=True, status=""),
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_payload_status_boolean_rejected(self) -> None:
        payload = _extraction_payload()
        payload["status"] = True
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                payload,
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_payload_status_unknown_string_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(with_status=True, status="weird"),
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_unsupported_source_type_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                _previous_source(),
                previous_period_source_type="fixture_json",
                previous_period_source_identifier="id",
            )

    def test_supported_source_types_accepted(self) -> None:
        for source_type in sorted(ALLOWED_PREVIOUS_PERIOD_SOURCE_TYPES):
            adapted = adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                _previous_source(),
                previous_period_source_type=source_type,
                previous_period_source_identifier="id",
            )
            self.assertEqual(
                adapted["audit"]["sources"]["previousPeriodSource"]["classification"],
                source_type,
            )

    def test_current_metadata_period_missing_rejected(self) -> None:
        metadata = _metadata()
        metadata = ReportMetadata(
            company_name=metadata.company_name,
            organization_number=metadata.organization_number,
            report_title=metadata.report_title,
            report_subtitle=metadata.report_subtitle,
            current_reporting_period=" ",
            previous_reporting_period=metadata.previous_reporting_period,
            city=metadata.city,
            fiscal_year=metadata.fiscal_year,
            document_year=metadata.document_year,
        )
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                metadata,
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_previous_metadata_period_missing_rejected(self) -> None:
        metadata = _metadata()
        metadata = ReportMetadata(
            company_name=metadata.company_name,
            organization_number=metadata.organization_number,
            report_title=metadata.report_title,
            report_subtitle=metadata.report_subtitle,
            current_reporting_period=metadata.current_reporting_period,
            previous_reporting_period=" ",
            city=metadata.city,
            fiscal_year=metadata.fiscal_year,
            document_year=metadata.document_year,
        )
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                metadata,
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_extractor_period_contradicts_metadata_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(period="2023-01-01\n-2023-12-31"),
                _metadata(),
                _previous_source(),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_matching_extractor_period_accepted(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(period="2025-01-01\n-2025-12-31"),
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="id",
        )
        self.assertTrue(adapted["audit"]["periodValidation"]["extractorEvidenceValidated"])

    def test_null_extractor_period_allowed_with_explicit_audit_state(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(period=None),
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="id",
        )
        self.assertFalse(adapted["audit"]["periodValidation"]["extractorEvidenceAvailable"])
        self.assertFalse(adapted["audit"]["periodValidation"]["extractorEvidenceValidated"])

    def test_previous_source_period_contradicts_metadata_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                _previous_source(period_label="2023-01-01\n-2023-12-31"),
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_matching_previous_source_period_sets_validated_true(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(period_label="2024-01-01\n-2024-12-31"),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="id",
        )
        self.assertTrue(adapted["audit"]["periodValidation"]["previousSourcePeriodValidated"])

    def test_missing_explicit_previous_period_source_rejected(self) -> None:
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                {},
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_previous_required_value_missing_key_rejected(self) -> None:
        previous = _previous_source()
        previous["values"].pop("revenue")
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                previous,
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_previous_required_value_null_rejected(self) -> None:
        previous = _previous_source()
        previous["values"]["revenue"] = None
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                previous,
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_previous_required_value_non_numeric_rejected(self) -> None:
        previous = _previous_source()
        previous["values"]["revenue"] = "N/A"
        with self.assertRaises(IncomeStatementAdapterError):
            adapt_income_statement_for_renderer(
                _extraction_payload(),
                _metadata(),
                previous,
                previous_period_source_type="synthetic_fixture",
                previous_period_source_identifier="id",
            )

    def test_load_previous_period_source_requires_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with self.assertRaises(IncomeStatementAdapterError):
                load_previous_period_source(missing)

    def test_load_previous_period_source_requires_values_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text(json.dumps({"periodLabel": "2024"}), encoding="utf-8")
            with self.assertRaises(IncomeStatementAdapterError):
                load_previous_period_source(p)

    def test_load_previous_period_source_rejects_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text("{bad", encoding="utf-8")
            with self.assertRaises(IncomeStatementAdapterError):
                load_previous_period_source(p)

    def test_load_previous_period_source_rejects_non_object_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            with self.assertRaises(IncomeStatementAdapterError):
                load_previous_period_source(p)

    def test_load_previous_period_source_rejects_null_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text(json.dumps({"values": None}), encoding="utf-8")
            with self.assertRaises(IncomeStatementAdapterError):
                load_previous_period_source(p)

    def test_adapter_output_is_directly_renderer_compatible(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(),
            previous_period_source_type="real_extract",
            previous_period_source_identifier="/tmp/prev.json",
        )

        with tempfile.TemporaryDirectory() as tmp:
            current_json = Path(tmp) / "current.json"
            previous_json = Path(tmp) / "previous.json"
            output_tex = Path(tmp) / "income.tex"
            current_json.write_text(
                json.dumps(adapted["rendererCurrentPayload"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            previous_json.write_text(
                json.dumps(adapted["rendererPreviousPayload"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            tex = render_income_statement_tex(
                current_json,
                output_tex,
                previous_period_fixture_path=previous_json,
            )
            self.assertIn("FinancialStatementBegin", tex)

    def test_audit_contains_all_documented_fields(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="data/mock/prev.json",
        )
        audit = adapted["audit"]
        for key in [
            "adapterVersion",
            "adapterStatus",
            "statusPolicy",
            "sources",
            "metadata",
            "lineValidation",
            "periodValidation",
            "presentationPeriods",
            "originalExtractionPayload",
        ]:
            self.assertIn(key, audit)

    def test_original_extraction_payload_in_audit_is_defensively_copied(self) -> None:
        extraction = _extraction_payload()
        extraction_original = deepcopy(extraction)
        adapted = adapt_income_statement_for_renderer(
            extraction,
            _metadata(),
            _previous_source(),
            previous_period_source_type="manual_override",
            previous_period_source_identifier="id",
        )

        extraction["lines"]["revenue"]["value"] = "999999"
        self.assertEqual(
            adapted["audit"]["originalExtractionPayload"]["lines"]["revenue"]["value"],
            extraction_original["lines"]["revenue"]["value"],
        )

    def test_audit_marks_synthetic_source_explicitly(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(),
            previous_period_source_type="synthetic_fixture",
            previous_period_source_identifier="data/mock/income_statement_previous_period_fixture.json",
        )
        source_info = adapted["audit"]["sources"]["previousPeriodSource"]
        self.assertEqual(source_info["classification"], "synthetic_fixture")
        self.assertTrue(source_info["isSyntheticComparisonSource"])

    def test_audit_marks_real_extract_source_explicitly(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(),
            previous_period_source_type="real_extract",
            previous_period_source_identifier="/tmp/real_prev.json",
        )
        source_info = adapted["audit"]["sources"]["previousPeriodSource"]
        self.assertEqual(source_info["classification"], "real_extract")
        self.assertFalse(source_info["isSyntheticComparisonSource"])

    def test_audit_marks_manual_override_source_explicitly(self) -> None:
        adapted = adapt_income_statement_for_renderer(
            _extraction_payload(),
            _metadata(),
            _previous_source(),
            previous_period_source_type="manual_override",
            previous_period_source_identifier="/tmp/manual_override_prev.json",
        )
        source_info = adapted["audit"]["sources"]["previousPeriodSource"]
        self.assertEqual(source_info["classification"], "manual_override")
        self.assertFalse(source_info["isSyntheticComparisonSource"])


if __name__ == "__main__":
    unittest.main()
