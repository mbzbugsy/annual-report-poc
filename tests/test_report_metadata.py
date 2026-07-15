from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from report_metadata import load_report_metadata


VALID_METADATA = {
    "companyName": "Omegapoint Malmö AB",
    "organizationNumber": "556613-1339",
    "reportTitle": "Årsredovisning 2025",
    "reportSubtitle": "Proof of concept med fiktiva uppgifter",
    "currentReportingPeriod": "2025-01-01\n-2025-12-31",
    "previousReportingPeriod": "2024-01-01\n-2024-12-31",
    "city": "Göteborg",
    "reportYear": "2026",
}


class ReportMetadataValidationTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_missing_field_rejected(self) -> None:
        payload = dict(VALID_METADATA)
        payload.pop("city")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            self._write_json(path, payload)

            with self.assertRaises(ValueError) as ctx:
                load_report_metadata(path)

        self.assertIn("Missing required report metadata fields", str(ctx.exception))
        self.assertIn("city", str(ctx.exception))

    def test_null_value_rejected(self) -> None:
        payload = dict(VALID_METADATA)
        payload["organizationNumber"] = None

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            self._write_json(path, payload)

            with self.assertRaises(ValueError) as ctx:
                load_report_metadata(path)

        self.assertIn("organizationNumber", str(ctx.exception))
        self.assertIn("expected non-empty string", str(ctx.exception))

    def test_numeric_value_rejected(self) -> None:
        payload = dict(VALID_METADATA)
        payload["reportYear"] = 2026

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            self._write_json(path, payload)

            with self.assertRaises(ValueError) as ctx:
                load_report_metadata(path)

        self.assertIn("reportYear", str(ctx.exception))
        self.assertIn("expected non-empty string", str(ctx.exception))

    def test_empty_string_rejected(self) -> None:
        payload = dict(VALID_METADATA)
        payload["companyName"] = ""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            self._write_json(path, payload)

            with self.assertRaises(ValueError) as ctx:
                load_report_metadata(path)

        self.assertIn("companyName", str(ctx.exception))
        self.assertIn("non-empty string", str(ctx.exception))

    def test_whitespace_only_string_rejected(self) -> None:
        payload = dict(VALID_METADATA)
        payload["reportSubtitle"] = "   \n\t"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            self._write_json(path, payload)

            with self.assertRaises(ValueError) as ctx:
                load_report_metadata(path)

        self.assertIn("reportSubtitle", str(ctx.exception))
        self.assertIn("non-empty string", str(ctx.exception))

    def test_valid_metadata_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.json"
            self._write_json(path, VALID_METADATA)

            metadata = load_report_metadata(path)

        self.assertEqual(metadata.company_name, VALID_METADATA["companyName"])
        self.assertEqual(metadata.organization_number, VALID_METADATA["organizationNumber"])
        self.assertEqual(metadata.report_title, VALID_METADATA["reportTitle"])
        self.assertEqual(metadata.current_reporting_period, VALID_METADATA["currentReportingPeriod"])


if __name__ == "__main__":
    unittest.main()
