from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_extractor import ExtractionError, extract_income_statement


def _xlsx_with_rr_sheet(file_path: Path, rows: list[dict[str, object]]) -> None:
    sheet_rows: list[str] = []
    max_row = 0
    for row in rows:
        row_idx = int(row["row"])
        max_row = max(max_row, row_idx)
        cells_xml: list[str] = []

        label = row.get("label")
        if label is not None:
            cells_xml.append(
                f'<c r="A{row_idx}" t="inlineStr"><is><t>{label}</t></is></c>'
            )

        prev = row.get("prev")
        if prev is not None:
            if isinstance(prev, (int, float)):
                cells_xml.append(f"<c r=\"B{row_idx}\"><v>{prev}</v></c>")
            else:
                cells_xml.append(
                    f'<c r="B{row_idx}" t="inlineStr"><is><t>{prev}</t></is></c>'
                )

        curr = row.get("curr")
        curr_formula = row.get("curr_formula")
        if curr is not None or curr_formula:
            formula_xml = f"<f>{curr_formula}</f>" if curr_formula else ""
            if curr is None:
                cells_xml.append(f"<c r=\"D{row_idx}\">{formula_xml}</c>")
            else:
                if isinstance(curr, (int, float)):
                    cells_xml.append(
                        f"<c r=\"D{row_idx}\">{formula_xml}<v>{curr}</v></c>"
                    )
                else:
                    cells_xml.append(
                        f'<c r="D{row_idx}" t="inlineStr">{formula_xml}<is><t>{curr}</t></is></c>'
                    )

        sheet_rows.append(f"<row r=\"{row_idx}\">{''.join(cells_xml)}</row>")

    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:D{max_row or 1}"/>
  <sheetData>
    {''.join(sheet_rows)}
  </sheetData>
</worksheet>
"""

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""

    rels_root = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""

    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="RR sammanställning" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""

    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""

    merge_xml = ""
    merged_ranges: list[str] = []
    for row in rows:
        merged_ref = row.get("merged_label_range")
        if isinstance(merged_ref, str):
            merged_ranges.append(merged_ref)
    if merged_ranges:
        merge_items = "".join(f'<mergeCell ref="{ref}"/>' for ref in merged_ranges)
        merge_xml = f'<mergeCells count="{len(merged_ranges)}">{merge_items}</mergeCells>'

    sheet_xml = sheet_xml.replace("</sheetData>", f"</sheetData>{merge_xml}")

    with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels_root)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


BASE_ROWS = [
    {"row": 10, "label": "Nettoomsättning", "prev": "intermediate", "curr": 110.0, "curr_formula": "B10+C10"},
    {"row": 11, "label": "Övriga rörelseintäkter", "prev": "intermediate", "curr": 7.0},
    {"row": 12, "label": "Totala intäkter", "prev": "intermediate", "curr": 117.0},
    {"row": 13, "label": "Rörelseresultat", "prev": "intermediate", "curr": 15.0},
    {"row": 14, "label": "Resultat efter finansiella poster", "prev": "intermediate", "curr": 14.0},
    {"row": 15, "label": "Resultat före skatt", "prev": "intermediate", "curr": 14.0},
    {"row": 16, "label": "Skatt", "prev": "intermediate", "curr": -3.0},
    {"row": 17, "label": "Årets resultat", "prev": "intermediate", "curr": 11.0},
]


class IncomeStatementExtractionTests(unittest.TestCase):
    def test_successful_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "ok.xlsx"
            output = tmp_path / "out.json"
            _xlsx_with_rr_sheet(workbook, BASE_ROWS)

            result = extract_income_statement(workbook, output)

            self.assertEqual(result["lines"]["revenue"]["value"], "110.0")
            self.assertTrue(result["lines"]["revenue"]["sourceTrace"]["valueIsFormula"])
            self.assertEqual(result["lines"]["revenue"]["sourceTrace"]["valueCell"], "D10")
            self.assertEqual(result["source"]["file"], workbook.name)
            self.assertIsNone(result["period"]["reportingPeriod"])
            self.assertTrue(output.exists())

    def test_corrupt_xlsx_zip_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "corrupt.xlsx"
            output = Path(tmp) / "out.json"
            workbook.write_text("this is not a zip", encoding="utf-8")

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Invalid or corrupt XLSX file", str(ctx.exception))

    def test_missing_workbook_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "does-not-exist.xlsx"
            output = Path(tmp) / "out.json"

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Workbook does not exist", str(ctx.exception))

    def test_missing_expected_sheet_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "wrong-sheet.xlsx"
            output = tmp_path / "out.json"
            _xlsx_with_rr_sheet(workbook, BASE_ROWS)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output, sheet_name="Not Existing Sheet")

            self.assertIn("Expected sheet not found", str(ctx.exception))

    def test_missing_required_label_fails(self) -> None:
        rows = [row for row in BASE_ROWS if row["label"] != "Rörelseresultat"]
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "missing-label.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Required label not found", str(ctx.exception))

    def test_duplicate_ambiguous_label_fails(self) -> None:
        rows = BASE_ROWS + [
            {"row": 30, "label": "Nettoomsättning", "prev": 1.0, "curr": 2.0}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "dup.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Ambiguous label match", str(ctx.exception))

    def test_missing_numeric_value_fails(self) -> None:
        rows = [dict(row) for row in BASE_ROWS]
        for row in rows:
            if row["label"] == "Resultat före skatt":
                row["curr"] = None
                break

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "missing-number.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Missing numeric value", str(ctx.exception))

    def test_formula_without_cached_value_fails_explicitly(self) -> None:
        rows = [dict(row) for row in BASE_ROWS]
        for row in rows:
            if row["label"] == "Rörelseresultat":
                row["curr"] = None
                row["curr_formula"] = "B13+C13"
                break

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "formula-no-cache.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Formula cell has no cached value", str(ctx.exception))

    def test_invalid_non_numeric_value_fails(self) -> None:
        rows = [dict(row) for row in BASE_ROWS]
        for row in rows:
            if row["label"] == "Årets resultat":
                row["curr"] = "not-a-number"
                break

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "not-number.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Non-numeric value", str(ctx.exception))

    def test_merged_cell_label_in_anchor_column_is_supported(self) -> None:
        rows = [dict(row) for row in BASE_ROWS]
        for row in rows:
            if row["label"] == "Resultat före skatt":
                row["merged_label_range"] = "A15:B15"
                break

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "merged-anchor.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            result = extract_income_statement(workbook, output)
            self.assertEqual(result["lines"]["profitBeforeTax"]["value"], "14.0")
            self.assertEqual(result["lines"]["profitBeforeTax"]["sourceTrace"]["valueCell"], "D15")

    def test_text_match_in_non_anchor_column_does_not_count(self) -> None:
        rows = [dict(row) for row in BASE_ROWS]
        for row in rows:
            if row["label"] == "Rörelseresultat":
                row["label"] = "Different label"
                row["prev"] = "Rörelseresultat"
                break

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "non-anchor-match.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            with self.assertRaises(ExtractionError) as ctx:
                extract_income_statement(workbook, output)

            self.assertIn("Required label not found", str(ctx.exception))

    def test_optional_mappings_absent_do_not_fail_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "optional-missing.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, BASE_ROWS)

            result = extract_income_statement(workbook, output)

            self.assertNotIn("costOfGoodsAndServices", result["lines"])
            self.assertNotIn("totalOperatingCosts", result["lines"])
            self.assertNotIn("netFinancialItems", result["lines"])

    def test_optional_mappings_are_extracted_when_present(self) -> None:
        rows = [dict(row) for row in BASE_ROWS] + [
            {"row": 21, "label": "Kostnad sålda varor och tjänster", "curr": -10.0},
            {"row": 22, "label": "Övriga externa kostnader", "curr": -20.0},
            {"row": 23, "label": "Personalkostnader", "curr": -30.0},
            {"row": 24, "label": "Av-/Nedskrivningar", "curr": -5.0},
            {"row": 25, "label": "Övriga rörelsekostnader", "curr": -1.0},
            {"row": 26, "label": "Rörelsens kostnader", "curr": -66.0},
            {"row": 34, "label": "Ränteintäkter", "curr": 9.0},
            {"row": 35, "label": "Räntekostnader", "curr": -4.0},
            {"row": 38, "label": "Bokslutsdispositioner", "curr": 0.0},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "optional-present.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            result = extract_income_statement(workbook, output)

            self.assertEqual(result["lines"]["costOfGoodsAndServices"]["value"], "-10.0")
            self.assertEqual(result["lines"]["totalOperatingCosts"]["value"], "-66.0")
            self.assertEqual(result["lines"]["appropriations"]["value"], "0.0")

    def test_authoritative_total_operating_costs_value_wins_over_component_sum(self) -> None:
        rows = [
            {"row": 10, "label": "Nettoomsättning", "curr": 200.0},
            {"row": 11, "label": "Övriga rörelseintäkter", "curr": 20.0},
            {"row": 12, "label": "Totala intäkter", "curr": 220.0},
            {"row": 13, "label": "Rörelseresultat", "curr": 50.0},
            {"row": 14, "label": "Resultat efter finansiella poster", "curr": 44.0},
            {"row": 15, "label": "Resultat före skatt", "curr": 44.0},
            {"row": 16, "label": "Skatt", "curr": -9.0},
            {"row": 17, "label": "Årets resultat", "curr": 35.0},
            {"row": 20, "label": "Rörelsens kostnader"},
            {"row": 21, "label": "Kostnad sålda varor och tjänster", "curr": -10.0},
            {"row": 22, "label": "Övriga externa kostnader", "curr": -20.0},
            {"row": 23, "label": "Personalkostnader", "curr": -30.0},
            {"row": 24, "label": "Av-/Nedskrivningar", "curr": -5.0},
            {"row": 25, "label": "Övriga rörelsekostnader", "curr": -1.0},
            {"row": 26, "label": "Rörelsens kostnader", "curr": -70.0},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "authoritative-total-costs.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            result = extract_income_statement(workbook, output)

            self.assertEqual(result["lines"]["totalOperatingCosts"]["value"], "-70.0")
            self.assertEqual(result["lines"]["totalOperatingCosts"]["sourceTrace"]["valueCell"], "D26")

    def test_net_financial_items_is_derived_from_interest_rows(self) -> None:
        rows = [
            {"row": 10, "label": "Nettoomsättning", "curr": 100.0},
            {"row": 11, "label": "Övriga rörelseintäkter", "curr": 10.0},
            {"row": 12, "label": "Totala intäkter", "curr": 110.0},
            {"row": 13, "label": "Rörelseresultat", "curr": 40.0},
            {"row": 14, "label": "Resultat efter finansiella poster", "curr": 33.0},
            {"row": 15, "label": "Resultat före skatt", "curr": 33.0},
            {"row": 16, "label": "Skatt", "curr": -7.0},
            {"row": 17, "label": "Årets resultat", "curr": 26.0},
            {"row": 30, "label": "Resultat från finansiella poster"},
            {"row": 34, "label": "Ränteintäkter", "curr": 8.0},
            {"row": 35, "label": "Räntekostnader", "curr": -3.0},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "net-fin-derived.xlsx"
            output = Path(tmp) / "out.json"
            _xlsx_with_rr_sheet(workbook, rows)

            result = extract_income_statement(workbook, output)

            self.assertEqual(result["lines"]["netFinancialItems"]["value"], "5.0")
            self.assertEqual(
                result["lines"]["netFinancialItems"]["sourceTrace"]["derivedFrom"],
                ["interestIncome", "interestCosts"],
            )
            self.assertIn(
                "section row has no authoritative numeric value in column D",
                result["lines"]["netFinancialItems"]["sourceTrace"]["derivationNote"],
            )


if __name__ == "__main__":
    unittest.main()
