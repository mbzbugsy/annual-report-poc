from __future__ import annotations

import subprocess
import tempfile
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
            "fiscalYear",
            "documentYear",
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

    def test_year_semantics_are_wired_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report-metadata.tex"
            subprocess.run(
                [
                    "python3",
                    "tools/render_report_metadata_tex.py",
                    "--input",
                    "data/report_metadata.json",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
            )

            generated_tex = output.read_text(encoding="utf-8")

        layout_source = (ROOT / "template" / "layout.tex").read_text(encoding="utf-8")
        title_page_source = (ROOT / "template" / "title-page.tex").read_text(encoding="utf-8")

        self.assertIn("\\newcommand{\\fiscalyear}{2025}", generated_tex)
        self.assertIn("\\newcommand{\\documentyear}{2026}", generated_tex)
        self.assertIn("\\fancyhead[R]{\\fiscalyear}", layout_source)
        self.assertIn("\\reportcity, \\documentyear", title_page_source)

    def test_income_slice_cli_requires_explicit_source_type(self) -> None:
        result = subprocess.run(
            [
                "python3",
                "tools/build_income_statement_slice.py",
                "--previous-period-source",
                "/tmp/does-not-matter.json",
            ],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--previous-period-source-type", result.stderr)

    def test_income_slice_cli_rejects_unsupported_source_type(self) -> None:
        result = subprocess.run(
            [
                "python3",
                "tools/build_income_statement_slice.py",
                "--previous-period-source",
                "/tmp/does-not-matter.json",
                "--previous-period-source-type",
                "fixture_json",
            ],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_readme_real_pipeline_example_clarifies_synthetic_comparison_mode(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("--previous-period-source-type real_extract", readme)
        self.assertIn("--previous-period-source-type synthetic_fixture", readme)
        self.assertIn("does not produce a fully real two-period report", readme)


if __name__ == "__main__":
    unittest.main()
