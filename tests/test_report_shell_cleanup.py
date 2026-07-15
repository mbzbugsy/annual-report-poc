from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReportShellCleanupTests(unittest.TestCase):
    def test_title_page_has_no_copilot_artifact(self) -> None:
        title_page = (ROOT / "template" / "title-page.tex").read_text(encoding="utf-8")
        self.assertNotIn("GitHub Copilot: Show Status", title_page)

    def test_central_metadata_source_exists_with_required_fields(self) -> None:
        metadata = (ROOT / "data" / "report_metadata.json").read_text(encoding="utf-8")
        for field in [
            "companyName",
            "organizationNumber",
            "reportTitle",
            "currentReportingPeriod",
            "previousReportingPeriod",
            "city",
            "reportYear",
        ]:
            self.assertIn(field, metadata)

    def test_renderer_does_not_hardcode_company_or_org(self) -> None:
        renderer_source = (ROOT / "src" / "income_statement_renderer.py").read_text(encoding="utf-8")
        self.assertNotIn("INCOME_STATEMENT_COMPANY_NAME", renderer_source)
        self.assertNotIn("INCOME_STATEMENT_ORGANIZATION_NUMBER", renderer_source)

    def test_layout_uses_generated_metadata_partial(self) -> None:
        layout_source = (ROOT / "template" / "layout.tex").read_text(encoding="utf-8")
        self.assertIn("\\input{generated/report-metadata.tex}", layout_source)
        self.assertNotIn("\\newcommand{\\companyname}", layout_source)


if __name__ == "__main__":
    unittest.main()
