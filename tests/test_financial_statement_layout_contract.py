from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FinancialStatementLayoutContractTests(unittest.TestCase):
    def test_shared_header_uses_company_and_orgnr_on_left(self) -> None:
        source = (ROOT / "template" / "financial-statement-layout.tex").read_text(encoding="utf-8")
        self.assertIn("Org.nr #2", source)
        self.assertIn("\\fancyhead[L]{\\fontfamily{phv}\\selectfont\\small \\shortstack[l]{\\FinancialStatementCompanyHeader}}", source)

    def test_page_indicator_is_parameterized(self) -> None:
        source = (ROOT / "template" / "financial-statement-layout.tex").read_text(encoding="utf-8")
        self.assertIn("\\providecommand{\\FinancialStatementBegin}[6]", source)
        self.assertIn("\\gdef\\FinancialStatementPageIndicator{#6}", source)

    def test_right_header_does_not_render_org_number(self) -> None:
        source = (ROOT / "template" / "financial-statement-layout.tex").read_text(encoding="utf-8")
        self.assertNotIn("\\fancyhead[R]{\\fontfamily{phv}\\selectfont\\small \\FinancialStatementOrganizationNumber}", source)
        self.assertIn("\\fancyhead[R]{\\fontfamily{phv}\\selectfont\\small \\FinancialStatementPageIndicator}", source)

    def test_no_header_rule_and_no_bottom_centered_page_number(self) -> None:
        source = (ROOT / "template" / "financial-statement-layout.tex").read_text(encoding="utf-8")
        self.assertIn("\\renewcommand{\\headrulewidth}{0pt}", source)
        self.assertNotIn("\\fancyfoot[C]{\\thepage}", source)


if __name__ == "__main__":
    unittest.main()
