from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cash_flow_renderer import RenderError, render_cash_flow_tex


REQUIRED_KEYS = [
    "resultAfterFinancialItems",
    "nonCashAdjustments",
    "incomeTaxPaid",
    "operatingCashFlowBeforeWorkingCapital",
    "changeInShortTermReceivables",
    "changeInShortTermLiabilities",
    "operatingCashFlowTotal",
    "intangibleComposedInvestingCashFlow",
    "investmentsTangibleAssets",
    "investmentsFinancialAssets",
    "investingCashFlowTotal",
    "financingCashFlowTotal",
    "netCashFlowForYear",
    "cashAtBeginning",
    "cashAtEnd",
]


class CashFlowRendererTests(unittest.TestCase):
    def _load_fixture(self) -> dict[str, object]:
        return json.loads((ROOT / "data/mock/cash_flow_fixture.json").read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _render(self, payload: dict[str, object], metadata_path: Path | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "cash.json"
            output_path = tmp_path / "cash.tex"
            self._write_json(input_path, payload)
            tex = render_cash_flow_tex(input_path, output_path, metadata_path=metadata_path)
            self.assertTrue(output_path.exists())
            return tex

    def test_valid_synthetic_fixture_renders(self) -> None:
        tex = self._render(self._load_fixture(), metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("{Kassaflödesanalys}", tex)
        self.assertIn("{8 (19)}", tex)
        self.assertIn("Rörelseresultat", tex)
        self.assertIn("Likvida medel vid årets slut", tex)

    def test_malformed_top_level_payload_rejected(self) -> None:
        base = self._load_fixture()
        cases = [
            ("top_level_array", [base], "Top-level payload must be a JSON object"),
            ("missing_schema_version", {k: v for k, v in base.items() if k != "schemaVersion"}, "schemaVersion"),
            ("blank_schema_version", {**base, "schemaVersion": "   "}, "schemaVersion"),
            (
                "missing_fixture_type_and_source",
                {k: v for k, v in base.items() if k not in {"fixtureType", "source"}},
                "fixtureType",
            ),
            ("lines_not_object", {**base, "lines": []}, "lines"),
            ("period_not_object", {**base, "period": []}, "period"),
        ]

        for name, payload, expected_message in cases:
            with self.subTest(case=name):
                with self.assertRaises(RenderError) as ctx:
                    self._render(payload)  # type: ignore[arg-type]
                self.assertIn(expected_message, str(ctx.exception))

    def test_all_required_properties_are_enforced(self) -> None:
        base = self._load_fixture()
        for key in REQUIRED_KEYS:
            with self.subTest(required_key=key):
                payload = copy.deepcopy(base)
                lines = payload["lines"]
                assert isinstance(lines, dict)
                lines.pop(key, None)
                with self.assertRaises(RenderError) as ctx:
                    self._render(payload)
                self.assertIn("Missing required cash-flow line", str(ctx.exception))

    def test_missing_required_property_rejected(self) -> None:
        payload = self._load_fixture()
        lines = payload["lines"]
        assert isinstance(lines, dict)
        lines.pop("operatingCashFlowTotal", None)
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("operatingCashFlowTotal", str(ctx.exception))

    def test_null_current_value_rejected(self) -> None:
        payload = self._load_fixture()
        lines = payload["lines"]
        assert isinstance(lines, dict)
        lines["incomeTaxPaid"]["valueCurrent"] = None
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("Missing value for 'incomeTaxPaid' (current)", str(ctx.exception))

    def test_null_previous_value_rejected(self) -> None:
        payload = self._load_fixture()
        lines = payload["lines"]
        assert isinstance(lines, dict)
        lines["incomeTaxPaid"]["valuePrevious"] = None
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("Missing value for 'incomeTaxPaid' (previous)", str(ctx.exception))

    def test_non_numeric_current_value_rejected(self) -> None:
        payload = self._load_fixture()
        lines = payload["lines"]
        assert isinstance(lines, dict)
        lines["incomeTaxPaid"]["valueCurrent"] = "abc"
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("Invalid decimal value", str(ctx.exception))

    def test_non_numeric_previous_value_rejected(self) -> None:
        payload = self._load_fixture()
        lines = payload["lines"]
        assert isinstance(lines, dict)
        lines["incomeTaxPaid"]["valuePrevious"] = "abc"
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("Invalid decimal value", str(ctx.exception))

    def test_status_review_required_rejected(self) -> None:
        payload = self._load_fixture()
        payload["status"] = "review_required"
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("status must be 'ok'", str(ctx.exception))

    def test_unresolved_supplied_line_status_rejected(self) -> None:
        payload = self._load_fixture()
        lines = payload["lines"]
        assert isinstance(lines, dict)
        lines["operatingCashFlowTotal"]["status"] = "unresolved"
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("unresolved status", str(ctx.exception))

    def test_missing_current_period_rejected(self) -> None:
        payload = self._load_fixture()
        period = payload["period"]
        assert isinstance(period, dict)
        period["currentPeriodLabel"] = ""
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("currentPeriodLabel", str(ctx.exception))

    def test_missing_previous_period_rejected(self) -> None:
        payload = self._load_fixture()
        period = payload["period"]
        assert isinstance(period, dict)
        period["previousPeriodLabel"] = ""
        with self.assertRaises(RenderError) as ctx:
            self._render(payload)
        self.assertIn("previousPeriodLabel", str(ctx.exception))

    def test_whitespace_only_period_labels_rejected(self) -> None:
        whitespace_value = "   \n  "
        base = self._load_fixture()

        for key in ("currentPeriodLabel", "previousPeriodLabel"):
            with self.subTest(period_key=key):
                payload = copy.deepcopy(base)
                period = payload["period"]
                assert isinstance(period, dict)
                period[key] = whitespace_value
                with self.assertRaises(RenderError) as ctx:
                    self._render(payload)
                self.assertIn(key, str(ctx.exception))

    def test_payload_period_contradicting_metadata_rejected(self) -> None:
        payload = self._load_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "companyName": "Example AB",
                        "organizationNumber": "556613-1339",
                        "reportTitle": "Årsredovisning 2025",
                        "reportSubtitle": "PoC",
                        "currentReportingPeriod": "2023-01-01\n-2023-12-31",
                        "previousReportingPeriod": "2022-01-01\n-2022-12-31",
                        "city": "Göteborg",
                        "fiscalYear": "2025",
                        "documentYear": "2026",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RenderError) as ctx:
                self._render(payload, metadata_path=metadata_path)
        self.assertIn("contradicts report metadata", str(ctx.exception))

    def test_current_and_previous_columns_are_not_swapped(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["resultAfterFinancialItems"]["valueCurrent"] = "111"
        payload["lines"]["resultAfterFinancialItems"]["valuePrevious"] = "222"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("\\FinancialStatementNormalRow{Rörelseresultat}{24}{111}{222}", tex)
        self.assertNotIn("\\FinancialStatementNormalRow{Rörelseresultat}{24}{222}{111}", tex)

    def test_negative_values_render_correctly(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["incomeTaxPaid"]["valueCurrent"] = "-1234.4"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("{-1 234}", tex)

    def test_zero_values_render_correctly(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["investmentsFinancialAssets"]["valueCurrent"] = "0"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("{0}", tex)

    def test_half_up_rounding_boundary_is_preserved(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["incomeTaxPaid"]["valueCurrent"] = "1234.5"
        payload["lines"]["incomeTaxPaid"]["valuePrevious"] = "-1234.5"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("\\FinancialStatementNormalRow{Betald inkomstskatt}{}{1 235}{-1 235}", tex)

    def test_financing_row_hidden_when_both_periods_zero(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["financingCashFlowTotal"]["valueCurrent"] = "0"
        payload["lines"]["financingCashFlowTotal"]["valuePrevious"] = "0"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertNotIn("Finansieringsverksamheten", tex)
        self.assertNotIn("Kassaflöde från finansieringsverksamheten", tex)

    def test_financing_row_shown_when_current_period_is_non_zero(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["financingCashFlowTotal"]["valueCurrent"] = "1"
        payload["lines"]["financingCashFlowTotal"]["valuePrevious"] = "0"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("Finansieringsverksamheten", tex)
        self.assertIn("Kassaflöde från finansieringsverksamheten", tex)

    def test_financing_row_shown_when_previous_period_is_non_zero(self) -> None:
        payload = self._load_fixture()
        payload["lines"]["financingCashFlowTotal"]["valueCurrent"] = "0"
        payload["lines"]["financingCashFlowTotal"]["valuePrevious"] = "1"
        tex = self._render(payload, metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("Finansieringsverksamheten", tex)
        self.assertIn("Kassaflöde från finansieringsverksamheten", tex)

    def test_exact_page_indicator_and_title(self) -> None:
        tex = self._render(self._load_fixture(), metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("{Kassaflödesanalys}", tex)
        self.assertIn("{8 (19)}", tex)

    def test_known_semantic_labels_remain_exact(self) -> None:
        tex = self._render(self._load_fixture(), metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("\\FinancialStatementNormalRow{Rörelseresultat}{24}", tex)
        self.assertIn(
            "\\FinancialStatementNormalRow{Försäljning av immateriella anläggningstillgångar}{}",
            tex,
        )

    def test_generated_tex_uses_shared_statement_primitives(self) -> None:
        tex = self._render(self._load_fixture(), metadata_path=ROOT / "data/report_metadata.json")
        self.assertIn("\\FinancialStatementBegin", tex)
        self.assertIn("\\FinancialStatementSectionRow", tex)
        self.assertIn("\\FinancialStatementNormalRow", tex)
        self.assertIn("\\FinancialStatementTotalRow", tex)
        self.assertNotIn("\\thispagestyle{fancy}", tex)

    def test_exact_required_row_order(self) -> None:
        tex = self._render(self._load_fixture(), metadata_path=ROOT / "data/report_metadata.json")
        ordered_markers = [
            "\\FinancialStatementNormalRow{Rörelseresultat}{24}",
            "\\FinancialStatementNormalRow{Justeringar för poster som inte ingår i kassaflödet}{25}",
            "\\FinancialStatementNormalRow{Betald inkomstskatt}{}",
            "\\FinancialStatementTotalRow{Kassaflöde från den löpande verksamheten före förändring av rörelsekapital}{}",
            "\\FinancialStatementNormalRow{Förändring av kortfristiga fordringar}{}",
            "\\FinancialStatementNormalRow{Förändring av kortfristiga skulder}{}",
            "\\FinancialStatementTotalRow{Kassaflöde från den löpande verksamheten}{}",
            "\\FinancialStatementNormalRow{Försäljning av immateriella anläggningstillgångar}{}",
            "\\FinancialStatementNormalRow{Investeringar i materiella anläggningstillgångar}{}",
            "\\FinancialStatementNormalRow{Investeringar i finansiella anläggningstillgångar}{}",
            "\\FinancialStatementTotalRow{Kassaflöde från investeringsverksamheten}{}",
            "\\FinancialStatementTotalRow{Årets kassaflöde}{}",
            "\\FinancialStatementNormalRow{Likvida medel vid årets början}{}",
            "\\FinancialStatementTotalRow{Likvida medel vid årets slut}{22}",
        ]
        positions = [tex.find(marker) for marker in ordered_markers]
        self.assertTrue(all(pos >= 0 for pos in positions))
        self.assertEqual(positions, sorted(positions))

    def test_cash_flow_partial_is_included_after_balance_sheet(self) -> None:
        content = (ROOT / "content/financial-summary.tex").read_text(encoding="utf-8")
        idx_income = content.find("generated/income-statement.tex")
        idx_balance = content.find("generated/balance-sheet.tex")
        idx_cash = content.find("generated/cash-flow.tex")
        self.assertGreater(idx_income, -1)
        self.assertGreater(idx_balance, idx_income)
        self.assertGreater(idx_cash, idx_balance)

    def test_build_script_does_not_consume_real_cash_flow_artifacts(self) -> None:
        script = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
        self.assertNotIn("generated/cash-flow-extraction.json", script)
        self.assertNotIn("Kassaflödesanalys 2025 - Omegapoint Malmö.xlsx", script)

    def test_clean_default_pdf_build_contains_cash_flow_page(self) -> None:
        if shutil.which("latexmk") is None:
            self.skipTest("latexmk not available")
        if shutil.which("gs") is None:
            self.skipTest("Ghostscript not available")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            result = subprocess.run(
                ["./scripts/build.sh"],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((workspace / "generated/cash-flow.tex").exists())
            self.assertTrue((workspace / "build/annual-report.pdf").exists())

            pdf_text = subprocess.run(
                [
                    "gs",
                    "-q",
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-sDEVICE=txtwrite",
                    "-sOutputFile=-",
                    str(workspace / "build/annual-report.pdf"),
                ],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(pdf_text.returncode, 0, msg=pdf_text.stderr)
            self.assertIn("Kassaflödesanalys", pdf_text.stdout)
            self.assertIn("8(19)", pdf_text.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
