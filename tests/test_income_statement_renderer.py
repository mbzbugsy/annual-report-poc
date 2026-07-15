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

from income_statement_renderer import RenderError, escape_latex, render_income_statement_tex


VALID_LINES = {
    "revenue": {"value": "123536980"},
    "otherOperatingIncome": {"value": "1763448.79999992"},
    "totalIncome": {"value": "125300428.79999992"},
    "operatingResult": {"value": "2262087.4099988788"},
    "resultAfterFinancialItems": {"value": "2197355.7799988291"},
    "profitBeforeTax": {"value": "2197355.7799988291"},
    "taxForYear": {"value": "-2164031.0000000098"},
    "netResult": {"value": "33324.779998819344"},
}


def _write_json(path: Path, lines: dict) -> None:
    payload = {
        "schemaVersion": "1.0",
        "source": {"file": "source-data/file.xlsx", "sheet": "RR sammanställning"},
        "lines": lines,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class IncomeStatementRendererTests(unittest.TestCase):
    def test_committed_synthetic_current_period_fixture_renders(self) -> None:
        fixture_current = ROOT / "data/mock/income_statement_current_period_fixture.json"
        fixture_previous = ROOT / "data/mock/income_statement_previous_period_fixture.json"

        with tempfile.TemporaryDirectory() as tmp:
            output_tex = Path(tmp) / "income.tex"
            tex = render_income_statement_tex(
                fixture_current,
                output_tex,
                previous_period_fixture_path=fixture_previous,
            )

            self.assertTrue(output_tex.exists())
            self.assertIn("Resultaträkning", tex)
            self.assertIn("Rörelsens intäkter", tex)
            self.assertIn("Rörelsens kostnader", tex)
            self.assertIn("Årets resultat", tex)
            self.assertIn("120 000 000", tex)

    def test_successful_json_parsing_and_render_contains_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "income.json"
            output_tex = tmp_path / "income.tex"
            _write_json(input_json, VALID_LINES)

            tex = render_income_statement_tex(input_json, output_tex)

            self.assertTrue(output_tex.exists())
            self.assertNotIn("\\input{template/financial-statement-layout.tex}", tex)
            self.assertIn(
                "\\FinancialStatementBegin{Omegapoint Malmö AB}{556613-1339}{Resultaträkning}",
                tex,
            )
            self.assertNotIn("\\thispagestyle{fancy}", tex)
            self.assertNotIn("\\fancyhead[L]", tex)
            self.assertIn("\\FinancialStatementSectionRow", tex)
            self.assertIn("\\FinancialStatementSubtotalRow", tex)
            self.assertIn("\\FinancialStatementTotalRow", tex)
            self.assertIn("\\FinancialStatementPreFinalTotalSpace", tex)
            self.assertNotIn("\\FinancialStatementPreNetResultSpace", tex)
            self.assertIn("Resultaträkning", tex)
            self.assertIn("Nettoomsättning", tex)
            self.assertIn("Övriga rörelseintäkter", tex)
            self.assertIn("Summa intäkter", tex)
            self.assertIn("Rörelseresultat", tex)
            self.assertIn("Resultat efter finansiella poster", tex)
            self.assertIn("Resultat före skatt", tex)
            self.assertIn("Skatt på årets resultat", tex)
            self.assertIn("Årets resultat", tex)

    def test_missing_required_income_statement_line_fails(self) -> None:
        lines = dict(VALID_LINES)
        lines.pop("operatingResult")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "income.json"
            output_tex = tmp_path / "income.tex"
            _write_json(input_json, lines)

            with self.assertRaises(RenderError) as ctx:
                render_income_statement_tex(input_json, output_tex)

            self.assertIn("Missing required income-statement line", str(ctx.exception))

    def test_invalid_decimal_value_fails(self) -> None:
        lines = dict(VALID_LINES)
        lines["revenue"] = {"value": "abc"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "income.json"
            output_tex = tmp_path / "income.tex"
            _write_json(input_json, lines)

            with self.assertRaises(RenderError) as ctx:
                render_income_statement_tex(input_json, output_tex)

            self.assertIn("Invalid decimal value", str(ctx.exception))

    def test_correct_latex_escaping(self) -> None:
        escaped = escape_latex("A&B_#%$~^{}\\")
        self.assertEqual(
            escaped,
            "A\\&B\\_\\#\\%\\$\\textasciitilde{}\\textasciicircum{}\\{\\}\\textbackslash{}",
        )

    def test_negative_value_rendering(self) -> None:
        lines = dict(VALID_LINES)
        lines["taxForYear"] = {"value": "-2164031.4"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "income.json"
            output_tex = tmp_path / "income.tex"
            _write_json(input_json, lines)

            tex = render_income_statement_tex(input_json, output_tex)

            self.assertIn("-2 164 031", tex)

    def test_malformed_previous_period_fixture_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "income.json"
            output_tex = tmp_path / "income.tex"
            fixture = tmp_path / "previous-fixture.json"
            _write_json(input_json, VALID_LINES)
            fixture.write_text('{"periodLabel": "20X4", "values": [1,2,3]}', encoding="utf-8")

            with self.assertRaises(RenderError) as ctx:
                render_income_statement_tex(
                    input_json,
                    output_tex,
                    previous_period_fixture_path=fixture,
                )

            self.assertIn("must contain an object field 'values'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
