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

from balance_sheet_renderer import RenderError, escape_latex, render_balance_sheet_tex


def _load_current_fixture() -> dict:
    return json.loads((ROOT / "data/mock/balance_sheet_current_period_fixture.json").read_text(encoding="utf-8"))


def _load_previous_fixture() -> dict:
    return json.loads((ROOT / "data/mock/balance_sheet_previous_period_fixture.json").read_text(encoding="utf-8"))


class BalanceSheetRendererTests(unittest.TestCase):
    def test_successful_rendering(self) -> None:
        current_fixture = ROOT / "data/mock/balance_sheet_current_period_fixture.json"
        previous_fixture = ROOT / "data/mock/balance_sheet_previous_period_fixture.json"

        with tempfile.TemporaryDirectory() as tmp:
            output_tex = Path(tmp) / "balance.tex"
            tex = render_balance_sheet_tex(
                current_fixture,
                output_tex,
                previous_period_fixture_path=previous_fixture,
            )

            self.assertTrue(output_tex.exists())
            self.assertIn("Balansräkning", tex)
            self.assertIn("TILLGÅNGAR", tex)
            self.assertIn("EGET KAPITAL OCH SKULDER", tex)
            self.assertIn("{6 (19)}", tex)
            self.assertIn("{7 (19)}", tex)
            self.assertIn("{2025-12-31}", tex)
            self.assertIn("{20X4-12-31}", tex)

    def test_balance_sheet_uses_single_balance_dates_in_column_headings(self) -> None:
        current_fixture = ROOT / "data/mock/balance_sheet_current_period_fixture.json"
        previous_fixture = ROOT / "data/mock/balance_sheet_previous_period_fixture.json"

        with tempfile.TemporaryDirectory() as tmp:
            output_tex = Path(tmp) / "balance.tex"
            tex = render_balance_sheet_tex(
                current_fixture,
                output_tex,
                previous_period_fixture_path=previous_fixture,
            )

            # Both balance-sheet pages must use point-in-time dates, not full period ranges.
            self.assertEqual(tex.count("{2025-12-31}"), 2)
            self.assertEqual(tex.count("{20X4-12-31}"), 2)
            self.assertNotIn("2025-01-01 \\\\ -2025-12-31", tex)
            self.assertNotIn("20X4-01-01 \\\\ -20X4-12-31", tex)

    def test_balance_sheet_subsection_rows_use_italic_style(self) -> None:
        current_fixture = ROOT / "data/mock/balance_sheet_current_period_fixture.json"
        previous_fixture = ROOT / "data/mock/balance_sheet_previous_period_fixture.json"

        with tempfile.TemporaryDirectory() as tmp:
            output_tex = Path(tmp) / "balance.tex"
            tex = render_balance_sheet_tex(
                current_fixture,
                output_tex,
                previous_period_fixture_path=previous_fixture,
            )

            self.assertIn("\\FinancialStatementSubsectionRow{Immateriella anläggningstillgångar}", tex)
            self.assertIn("\\FinancialStatementSubsectionRow{Materiella anläggningstillgångar}", tex)
            self.assertIn("\\FinancialStatementSubsectionRow{Finansiella anläggningstillgångar}", tex)
            self.assertIn("\\FinancialStatementSubsectionRow{Kortfristiga fordringar}", tex)
            self.assertIn("\\FinancialStatementSubsectionRow{Bundet eget kapital}", tex)
            self.assertIn("\\FinancialStatementSubsectionRow{Fritt eget kapital}", tex)
            self.assertIn("\\FinancialStatementNormalRow{\\textit{\\hspace*{2mm}Kassa och bank}}", tex)

    def test_required_line_validation(self) -> None:
        current = _load_current_fixture()
        previous = _load_previous_fixture()
        current["lines"].pop("goodwill")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_path = tmp_path / "current.json"
            previous_path = tmp_path / "previous.json"
            output_tex = tmp_path / "balance.tex"
            current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            previous_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(RenderError) as ctx:
                render_balance_sheet_tex(current_path, output_tex, previous_period_fixture_path=previous_path)

            self.assertIn("Missing required balance-sheet line", str(ctx.exception))
            self.assertIn("goodwill", str(ctx.exception))

    def test_invalid_decimal_validation(self) -> None:
        current = _load_current_fixture()
        previous = _load_previous_fixture()
        current["lines"]["cashAndBank"]["value"] = "not-a-number"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_path = tmp_path / "current.json"
            previous_path = tmp_path / "previous.json"
            output_tex = tmp_path / "balance.tex"
            current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            previous_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(RenderError) as ctx:
                render_balance_sheet_tex(current_path, output_tex, previous_period_fixture_path=previous_path)

            self.assertIn("Invalid decimal value", str(ctx.exception))

    def test_latex_escaping(self) -> None:
        escaped = escape_latex("A&B_#%$~^{}\\")
        self.assertEqual(
            escaped,
            "A\\&B\\_\\#\\%\\$\\textasciitilde{}\\textasciicircum{}\\{\\}\\textbackslash{}",
        )

    def test_negative_number_formatting(self) -> None:
        current = _load_current_fixture()
        previous = _load_previous_fixture()
        current["lines"]["profitForYear"]["value"] = "-1234"

        # Keep balanced totals authoritative by matching equity side total manually.
        current["lines"]["totalUnrestrictedEquity"]["value"] = "35121890"
        current["lines"]["totalEquity"]["value"] = "35341890"
        current["lines"]["totalEquityAndLiabilities"]["value"] = "90820709"
        current["lines"]["totalShortTermLiabilities"]["value"] = "55478819"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_path = tmp_path / "current.json"
            previous_path = tmp_path / "previous.json"
            output_tex = tmp_path / "balance.tex"
            current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            previous_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")

            tex = render_balance_sheet_tex(current_path, output_tex, previous_period_fixture_path=previous_path)
            self.assertIn("-1 234", tex)

    def test_assets_and_liabilities_order(self) -> None:
        current_fixture = ROOT / "data/mock/balance_sheet_current_period_fixture.json"
        previous_fixture = ROOT / "data/mock/balance_sheet_previous_period_fixture.json"

        with tempfile.TemporaryDirectory() as tmp:
            output_tex = Path(tmp) / "balance.tex"
            tex = render_balance_sheet_tex(
                current_fixture,
                output_tex,
                previous_period_fixture_path=previous_fixture,
            )

            idx_assets = tex.find("TILLGÅNGAR")
            idx_assets_total = tex.find("SUMMA TILLGÅNGAR")
            idx_equity = tex.find("EGET KAPITAL OCH SKULDER")
            idx_total_equity = tex.find("SUMMA EGET KAPITAL OCH SKULDER")

            self.assertGreater(idx_assets, -1)
            self.assertGreater(idx_assets_total, idx_assets)
            self.assertGreater(idx_equity, idx_assets_total)
            self.assertGreater(idx_total_equity, idx_equity)

    def test_explicit_two_page_break_exists(self) -> None:
        current_fixture = ROOT / "data/mock/balance_sheet_current_period_fixture.json"
        previous_fixture = ROOT / "data/mock/balance_sheet_previous_period_fixture.json"

        with tempfile.TemporaryDirectory() as tmp:
            output_tex = Path(tmp) / "balance.tex"
            tex = render_balance_sheet_tex(
                current_fixture,
                output_tex,
                previous_period_fixture_path=previous_fixture,
            )

            self.assertIn("SUMMA TILLGÅNGAR", tex)
            self.assertIn("% Explicit statement boundary between assets and equity/liabilities pages.", tex)
            self.assertGreaterEqual(tex.count("\\FinancialStatementBegin"), 2)
            self.assertGreaterEqual(tex.count("\\FinancialStatementEnd"), 2)

    def test_unbalanced_fixture_rejected(self) -> None:
        current = _load_current_fixture()
        previous = _load_previous_fixture()
        current["lines"]["totalEquityAndLiabilities"]["value"] = "90820708"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_path = tmp_path / "current.json"
            previous_path = tmp_path / "previous.json"
            output_tex = tmp_path / "balance.tex"
            current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            previous_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(RenderError) as ctx:
                render_balance_sheet_tex(current_path, output_tex, previous_period_fixture_path=previous_path)

            self.assertIn("not balanced", str(ctx.exception))

    def test_previous_period_imbalance_rejected(self) -> None:
        current = _load_current_fixture()
        previous = _load_previous_fixture()
        previous["values"]["totalEquityAndLiabilities"] = "86245001"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_path = tmp_path / "current.json"
            previous_path = tmp_path / "previous.json"
            output_tex = tmp_path / "balance.tex"
            current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            previous_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(RenderError) as ctx:
                render_balance_sheet_tex(current_path, output_tex, previous_period_fixture_path=previous_path)

            self.assertIn("Previous-period fixture is not balanced", str(ctx.exception))
            self.assertIn("totalAssets differs from totalEquityAndLiabilities", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
