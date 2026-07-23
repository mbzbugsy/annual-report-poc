from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notes_workbook_extractor import (  # noqa: E402
    NotesWorkbookExtractionError,
    extract_notes_workbook_raw,
    raw_notes_workbook_contract_json_bytes,
)


def _default_mapping(path: Path, *, required_sheet: str = "Sheet1", authoritative_range: str = "A1:C3") -> None:
    payload = {
        "policyVersion": "1.0",
        "notesSchemaVersion": "1.0",
        "reportingEntityIdentity": {
            "companyName": {
                "authority": "metadata",
                "workbookEvidenceMode": "metadata_only",
            },
            "organizationNumber": {
                "authority": "metadata",
                "workbookEvidenceMode": "metadata_only",
                "diagnosticCode": "WORKBOOK_REPORTING_ENTITY_ORG_NUMBER_NOT_PRESENT",
            },
        },
        "canonicalNotes": [
            {
                "canonicalOrder": 1,
                "noteNumber": 1,
                "title": "Redovisnings- och värderingsprinciper",
                "authorityStatus": "workbook_direct",
                "source": {
                    "required": True,
                    "sheet": required_sheet,
                    "sourceType": "workbook_range",
                    "tableShapes": [
                        {
                            "range": authoritative_range,
                            "rowCount": 3,
                            "colCount": 3,
                        }
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _xlsx_fixture(
    path: Path,
    *,
    include_external_formula: bool = False,
    authoritative_formula_without_cached: bool = False,
    hidden_row: bool = True,
    hidden_col: bool = True,
    include_comments: bool = True,
    include_drawing: bool = True,
    malformed_workbook_xml: bool = False,
    malformed_worksheet_xml: bool = False,
    include_meaningful_object_rel: bool = False,
) -> None:
    content_types = """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>
  <Override PartName='/xl/styles.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'/>
  <Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
  <Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
  <Override PartName='/xl/comments1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml'/>
  <Override PartName='/xl/drawings/drawing1.xml' ContentType='application/vnd.openxmlformats-officedocument.drawing+xml'/>
  <Override PartName='/xl/externalLinks/externalLink1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml'/>
</Types>
"""

    root_rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>
</Relationships>
"""

    workbook_xml = """<?xml version='1.0' encoding='UTF-8'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <calcPr calcId='190029'/>
  <sheets>
    <sheet name='Sheet1' sheetId='1' r:id='rId1'/>
    <sheet name='HiddenSheet' sheetId='2' state='hidden' r:id='rId2'/>
  </sheets>
</workbook>
"""
    if malformed_workbook_xml:
        workbook_xml = "<workbook><broken>"

    workbook_rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>
  <Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/>
</Relationships>
"""

    styles_xml = """<?xml version='1.0' encoding='UTF-8'?>
<styleSheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <numFmts count='1'>
    <numFmt numFmtId='165' formatCode='#,##0.00'/>
  </numFmts>
  <fonts count='1'><font><sz val='11'/><name val='Calibri'/></font></fonts>
  <fills count='1'><fill><patternFill patternType='none'/></fill></fills>
  <borders count='1'><border/></borders>
  <cellStyleXfs count='1'><xf numFmtId='0' fontId='0' fillId='0' borderId='0'/></cellStyleXfs>
  <cellXfs count='2'>
    <xf numFmtId='0' fontId='0' fillId='0' borderId='0' xfId='0'/>
    <xf numFmtId='165' fontId='0' fillId='0' borderId='0' xfId='0' applyNumberFormat='1'/>
  </cellXfs>
</styleSheet>
"""

    row_hidden_attr = " hidden='1'" if hidden_row else ""
    col_hidden_attr = " hidden='1'" if hidden_col else ""

    formula_cell = "<c r='B2'><f>A2+1</f><v>43</v></c>"
    if authoritative_formula_without_cached:
        formula_cell = "<c r='B2'><f>A2+1</f></c>"
    if include_external_formula:
        formula_cell = "<c r='B2'><f>[1]Data!A1</f><v>43</v></c>"

    comment_ref_xml = "<legacyDrawing r:id='rId2'/>" if include_comments else ""
    drawing_ref_xml = "<drawing r:id='rId3'/>" if include_drawing else ""

    sheet1_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <dimension ref='A1:C4'/>
  <sheetViews><sheetView workbookViewId='0'><pane xSplit='1' ySplit='1' topLeftCell='B2' activePane='bottomRight' state='frozen'/></sheetView></sheetViews>
  <cols><col min='3' max='3' width='22.5' customWidth='1'{col_hidden_attr}/></cols>
  <sheetData>
    <row r='1'><c r='A1' t='inlineStr'><is><t>Omegapoint Malmö AB</t></is></c><c r='B1' t='inlineStr'><is><t>556613-1339</t></is></c></row>
    <row r='2'><c r='A2' s='1'><v>42</v></c>{formula_cell}</row>
    <row r='3'{row_hidden_attr}><c r='A3' t='inlineStr'><is><t>2025-01--2025-12</t></is></c><c r='B3' t='inlineStr'><is><t>Hej</t></is></c></row>
  </sheetData>
  <mergeCells count='1'><mergeCell ref='A3:B3'/></mergeCells>
  <dataValidations count='1'><dataValidation type='whole' sqref='A2'><formula1>0</formula1><formula2>100</formula2></dataValidation></dataValidations>
  {comment_ref_xml}
  {drawing_ref_xml}
</worksheet>
"""
    if malformed_worksheet_xml:
        sheet1_xml = "<worksheet><broken>"

    sheet2_xml = """<?xml version='1.0' encoding='UTF-8'?>
<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><dimension ref='A1'/><sheetData/></worksheet>
"""

    sheet1_rels_items = [
        "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink' Target='https://example.com' TargetMode='External'/>",
    ]
    if include_comments:
        sheet1_rels_items.append("<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments' Target='../comments1.xml'/>")
    if include_drawing:
        sheet1_rels_items.append("<Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing' Target='../drawings/drawing1.xml'/>")
    if include_meaningful_object_rel:
        sheet1_rels_items.append("<Relationship Id='rId4' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject' Target='../drawings/ole1.bin'/>")

    sheet1_rels = "<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>" + "".join(sheet1_rels_items) + "</Relationships>"

    comments_xml = """<?xml version='1.0' encoding='UTF-8'?>
<comments xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <authors><author>tester</author></authors>
  <commentList>
    <comment ref='B3' authorId='0'><text><r><t>Kommentar</t></r></text></comment>
  </commentList>
</comments>
"""

    drawing_xml = """<?xml version='1.0' encoding='UTF-8'?>
<xdr:wsDr xmlns:xdr='http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'>
  <xdr:twoCellAnchor>
    <xdr:from><xdr:col>0</xdr:col><xdr:row>0</xdr:row></xdr:from>
    <xdr:to><xdr:col>1</xdr:col><xdr:row>1</xdr:row></xdr:to>
    <xdr:sp/>
    <xdr:clientData/>
  </xdr:twoCellAnchor>
</xdr:wsDr>
"""

    external_link_xml = """<?xml version='1.0' encoding='UTF-8'?>
<externalLink xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
  <externalBook r:id='rId1'/>
</externalLink>
"""
    external_link_rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath' Target='file:///external.xlsx' TargetMode='External'/>
</Relationships>
"""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1_xml)
        zf.writestr("xl/worksheets/sheet2.xml", sheet2_xml)
        zf.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet1_rels)
        zf.writestr("xl/comments1.xml", comments_xml)
        zf.writestr("xl/drawings/drawing1.xml", drawing_xml)
        zf.writestr("xl/externalLinks/externalLink1.xml", external_link_xml)
        zf.writestr("xl/externalLinks/_rels/externalLink1.xml.rels", external_link_rels)


class NotesWorkbookExtractorTests(unittest.TestCase):
    def test_preserves_sheet_order_visibility_and_core_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)

            self.assertEqual(result["workbook"]["sheetOrder"], ["Sheet1", "HiddenSheet"])
            self.assertEqual(result["workbook"]["worksheetCount"], 2)
            self.assertEqual(result["workbook"]["formulaCellCount"], 1)
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(workbook.read_bytes()).hexdigest())
            self.assertEqual(result["workbook"]["authoritativeFormulaMissingCachedCount"], 0)

    def test_formula_and_cached_value_are_distinct_and_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)
            sheet1 = result["worksheets"][0]
            b2 = next(cell for cell in sheet1["cells"] if cell["coordinate"] == "B2")
            self.assertEqual(b2["formula"], "A2+1")
            self.assertEqual(b2["cachedValue"], "43")
            self.assertNotEqual(b2["formula"], b2["cachedValue"])

    def test_mapped_blank_cells_and_merged_ranges_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook)
            _default_mapping(mapping, authoritative_range="A1:C3")

            result = extract_notes_workbook_raw(workbook, mapping)
            sheet1 = result["worksheets"][0]
            self.assertIn("A3:B3", sheet1["mergedRanges"])
            coords = {cell["coordinate"] for cell in sheet1["cells"]}
            self.assertIn("C1", coords)
            c1 = next(cell for cell in sheet1["cells"] if cell["coordinate"] == "C1")
            self.assertEqual(c1["displayedValue"], "")

    def test_style_and_number_format_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)
            sheet1 = result["worksheets"][0]
            a2 = next(cell for cell in sheet1["cells"] if cell["coordinate"] == "A2")
            self.assertEqual(a2["styleId"], 1)
            self.assertEqual(a2["numberFormat"], "#,##0.00")

    def test_hidden_rows_and_columns_are_captured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, hidden_row=True, hidden_col=True)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)
            sheet1 = result["worksheets"][0]
            self.assertIn(3, sheet1["hiddenRows"])
            self.assertIn("C", sheet1["hiddenColumns"])

    def test_comments_are_detected_with_source_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, include_comments=True)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)
            sheet1 = result["worksheets"][0]
            b3 = next(cell for cell in sheet1["cells"] if cell["coordinate"] == "B3")
            self.assertIsNotNone(b3["commentEvidence"])
            self.assertEqual(b3["commentEvidence"]["sourcePart"], "xl/comments1.xml")

    def test_drawings_and_meaningful_objects_detected_with_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, include_meaningful_object_rel=True)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)
            codes = [d.get("code") for d in result["diagnostics"]]
            self.assertIn("WORKSHEET_DRAWING_RELATIONSHIP_PRESENT", codes)
            meaningful = [
                d for d in result["diagnostics"]
                if d.get("code") == "WORKSHEET_DRAWING_RELATIONSHIP_PRESENT"
                and isinstance(d.get("relationship"), dict)
                and d["relationship"].get("type") == "unsupportedMeaningfulObject"
            ]
            self.assertTrue(meaningful)
            self.assertEqual(meaningful[0]["sheet"], "Sheet1")

    def test_is_deterministic_and_has_no_runtime_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook)
            _default_mapping(mapping)

            first = raw_notes_workbook_contract_json_bytes(extract_notes_workbook_raw(workbook, mapping))
            second = raw_notes_workbook_contract_json_bytes(extract_notes_workbook_raw(workbook, mapping))

            self.assertEqual(first, second)
            text = first.decode("utf-8")
            self.assertNotIn("timestamp", text.lower())
            self.assertNotIn("duration", text.lower())

    def test_external_formula_with_cached_value_is_accepted_with_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, include_external_formula=True)
            _default_mapping(mapping)

            result = extract_notes_workbook_raw(workbook, mapping)
            codes = [diag["code"] for diag in result["diagnostics"]]
            self.assertIn("EXTERNAL_LINK_CACHED_VALUE_USED", codes)
            self.assertEqual(result["workbook"]["externalLinks"]["count"], 1)

    def test_formula_without_cached_value_in_authoritative_range_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, authoritative_formula_without_cached=True)
            _default_mapping(mapping)

            with self.assertRaises(NotesWorkbookExtractionError) as ctx:
                extract_notes_workbook_raw(workbook, mapping)
            self.assertIn("formula without cached value", str(ctx.exception).lower())

    def test_malformed_workbook_xml_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, malformed_workbook_xml=True)
            _default_mapping(mapping)

            with self.assertRaises(NotesWorkbookExtractionError) as ctx:
                extract_notes_workbook_raw(workbook, mapping)
            self.assertIn("malformed workbook xml", str(ctx.exception).lower())

    def test_malformed_worksheet_xml_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook, malformed_worksheet_xml=True)
            _default_mapping(mapping)

            with self.assertRaises(NotesWorkbookExtractionError) as ctx:
                extract_notes_workbook_raw(workbook, mapping)
            self.assertIn("malformed worksheet xml", str(ctx.exception).lower())

    def test_missing_workbook_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mapping = tmp_path / "mapping.json"
            _default_mapping(mapping)

            with self.assertRaises(NotesWorkbookExtractionError):
                extract_notes_workbook_raw(tmp_path / "missing.xlsx", mapping)

    def test_corrupt_zip_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "bad.xlsx"
            mapping = tmp_path / "mapping.json"
            _default_mapping(mapping)
            workbook.write_text("not-a-zip", encoding="utf-8")

            with self.assertRaises(NotesWorkbookExtractionError) as ctx:
                extract_notes_workbook_raw(workbook, mapping)
            self.assertIn("zip", str(ctx.exception).lower())

    def test_missing_required_worksheet_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "fixture.xlsx"
            mapping = tmp_path / "mapping.json"
            _xlsx_fixture(workbook)
            _default_mapping(mapping, required_sheet="DoesNotExist")

            with self.assertRaises(NotesWorkbookExtractionError) as ctx:
                extract_notes_workbook_raw(workbook, mapping)
            self.assertIn("missing required worksheet", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
