from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from management_report_docx_extractor import ExtractionError, extract_management_report_raw, raw_contract_json_bytes


def _core_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/' xmlns:dcterms='http://purl.org/dc/terms/'>
  <dc:creator>Unit Test</dc:creator>
  <cp:lastModifiedBy>Unit Test</cp:lastModifiedBy>
  <dcterms:created>2025-01-01T00:00:00Z</dcterms:created>
  <dcterms:modified>2026-01-01T00:00:00Z</dcterms:modified>
</cp:coreProperties>
"""


def _styles_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:styles xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:style w:type='paragraph' w:styleId='Normal'><w:name w:val='Normal'/></w:style>
  <w:style w:type='paragraph' w:styleId='Heading1'>
    <w:name w:val='heading 1'/>
    <w:pPr><w:outlineLvl w:val='0'/></w:pPr>
  </w:style>
</w:styles>
"""


def _rels_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
  <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles' Target='styles.xml'/>
  <Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering' Target='numbering.xml'/>
  <Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings' Target='settings.xml'/>
</Relationships>
"""


def _numbering_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:numbering xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>
"""


def _settings_xml(track_revisions: bool = False) -> str:
    body = "<w:trackRevisions/>" if track_revisions else ""
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:settings xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  %s
</w:settings>
""" % body


def _document_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val='Heading1'/></w:pPr>
      <w:r><w:rPr><w:b/></w:rPr><w:t>Förvaltningsberättelse</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Styrelsen ... 2025-01-01-2025-12-31.</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:rPr><w:i/></w:rPr><w:t>rad1</w:t><w:br/><w:t>rad2</w:t></w:r>
            <w:r><w:rPr><w:vanish/><w:u/></w:rPr><w:t>hemlig</w:t></w:r>
      <w:lastRenderedPageBreak/>
    </w:p>
    <w:p>
      <w:r><w:t>bryt</w:t><w:br w:type='page'/></w:r>
    </w:p>
    <w:tbl>
      <w:tblGrid>
        <w:gridCol/><w:gridCol/>
      </w:tblGrid>
      <w:tr>
        <w:tc><w:p><w:r><w:t>A1</w:t></w:r></w:p></w:tc>
                <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:tcPr><w:gridSpan w:val='2'/></w:tcPr><w:p><w:r><w:t>B1</w:t></w:r></w:p></w:tc>
      </w:tr>
            <w:tr>
                <w:tc>
                    <w:p>
                        <w:r><w:t>cell-unsupported</w:t></w:r>
                        <w:r><w:drawing/></w:r>
                        <w:r><w:pict/></w:r>
                        <w:r><w:instrText>REF test-field</w:instrText></w:r>
                        <w:r><w:txbxContent><w:p><w:r><w:t>textbox payload</w:t></w:r></w:p></w:txbxContent></w:r>
                        <w:r><w:rPr><w:vanish/></w:rPr><w:t>hemlig-cell</w:t></w:r>
                    </w:p>
                </w:tc>
            </w:tr>
    </w:tbl>
    <w:p>
      <w:r><w:t>slut</w:t></w:r>
      <w:pict/>
    </w:p>
    <w:sectPr/>
  </w:body>
</w:document>
"""


def _write_docx(path: Path, *, document_xml: str, include_comments: bool = False, track_revisions: bool = False) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", _styles_xml())
        zf.writestr("word/numbering.xml", _numbering_xml())
        zf.writestr("word/settings.xml", _settings_xml(track_revisions=track_revisions))
        zf.writestr("word/_rels/document.xml.rels", _rels_xml())
        zf.writestr("docProps/core.xml", _core_xml())
        if include_comments:
            zf.writestr(
                "word/comments.xml",
                """<?xml version='1.0' encoding='UTF-8'?><w:comments xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>""",
            )


class ManagementReportDocxExtractorTests(unittest.TestCase):
    def test_valid_docx_produces_ordered_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            raw = extract_management_report_raw(docx)

        self.assertEqual(raw["schemaVersion"], "1.0")
        blocks = raw["blocks"]
        self.assertGreater(len(blocks), 0)
        self.assertEqual([b["blockIndex"] for b in blocks], list(range(1, len(blocks) + 1)))
        self.assertEqual([b["blockId"] for b in blocks], [f"b{i:04d}" for i in range(1, len(blocks) + 1)])

    def test_repeated_extraction_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())

            raw_a = extract_management_report_raw(docx)
            raw_b = extract_management_report_raw(docx)
            self.assertEqual(raw_contract_json_bytes(raw_a), raw_contract_json_bytes(raw_b))

    def test_output_contains_no_wall_clock_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            raw = extract_management_report_raw(docx)
            dumped = raw_contract_json_bytes(raw).decode("utf-8")

        self.assertNotIn("extractedAtUtc", dumped)

    def test_source_sha256_is_correct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            expected = hashlib.sha256(docx.read_bytes()).hexdigest()
            raw = extract_management_report_raw(docx)

        self.assertEqual(raw["source"]["sha256"], expected)

    def test_exact_paragraph_text_and_run_flags_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            raw = extract_management_report_raw(docx)

        paragraphs = [b for b in raw["blocks"] if b["blockType"] == "paragraph"]
        self.assertEqual(paragraphs[0]["paragraph"]["text"], "Förvaltningsberättelse")
        self.assertEqual(paragraphs[0]["paragraph"]["styleId"], "Heading1")
        self.assertEqual(paragraphs[0]["paragraph"]["styleName"], "heading 1")
        self.assertEqual(paragraphs[0]["paragraph"]["headingLevel"], 1)

        p3 = paragraphs[2]["paragraph"]
        self.assertEqual(p3["text"], "rad1\nrad2hemlig")
        self.assertEqual(p3["runs"][0]["italic"], True)
        self.assertEqual(p3["runs"][1]["hidden"], True)
        self.assertEqual(p3["runs"][1]["underline"], True)

    def test_explicit_page_break_and_last_rendered_page_break_captured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            raw = extract_management_report_raw(docx)

        paragraphs = [b for b in raw["blocks"] if b["blockType"] == "paragraph"]
        self.assertTrue(paragraphs[2]["paragraph"]["lastRenderedPageBreak"])
        page_break_blocks = [b for b in raw["blocks"] if b["blockType"] == "explicitPageBreak"]
        self.assertEqual(len(page_break_blocks), 1)

    def test_table_dimensions_cells_gridspan_and_empty_cells_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            raw = extract_management_report_raw(docx)

        tables = [b for b in raw["blocks"] if b["blockType"] == "table"]
        self.assertEqual(len(tables), 1)
        table = tables[0]["table"]
        self.assertEqual(table["rowCount"], 3)
        self.assertEqual(table["gridColumnCount"], 2)
        self.assertEqual(table["rows"][0]["cells"][0]["text"], "A1")
        self.assertEqual(table["rows"][0]["cells"][1]["text"], "")
        self.assertEqual(table["rows"][1]["cells"][0]["gridSpan"], 2)

    def test_table_cell_unsupported_flags_and_hidden_diagnostic_trace_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=_document_xml())
            raw = extract_management_report_raw(docx)

        table_block = next(b for b in raw["blocks"] if b["blockType"] == "table")
        cell_para = table_block["table"]["rows"][2]["cells"][0]["paragraphs"][0]
        flags = cell_para["attachedUnsupportedConstructs"]
        self.assertEqual(flags["containsDrawing"], True)
        self.assertEqual(flags["containsPict"], True)
        self.assertEqual(flags["containsTextBox"], True)
        self.assertEqual(flags["containsFieldCode"], True)

        hidden_diags = [d for d in raw["diagnostics"] if d.get("code") == "HIDDEN_TEXT_DETECTED"]
        table_hidden = [
            d for d in hidden_diags
            if isinstance(d.get("sourceTrace"), dict)
            and d["sourceTrace"].get("tableIndex") == 1
            and d["sourceTrace"].get("rowIndex") == 3
            and d["sourceTrace"].get("cellIndex") == 1
            and d["sourceTrace"].get("cellParagraphIndex") == 1
        ]
        self.assertEqual(len(table_hidden), 1)
        self.assertTrue(isinstance(table_hidden[0]["sourceTrace"].get("runIndex"), int))
        self.assertIn(table_hidden[0]["sourceTrace"].get("runIndex"), table_hidden[0]["sourceTrace"].get("runIndices", []))

    def test_drawing_and_pict_diagnostics_are_preserved(self) -> None:
        doc_xml = _document_xml().replace("<w:pict/>", "<w:pict/><w:drawing/>")
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=doc_xml)
            raw = extract_management_report_raw(docx)
        codes = {d["code"] for d in raw["diagnostics"]}
        self.assertIn("UNSUPPORTED_PICT_DETECTED", codes)
        self.assertIn("UNSUPPORTED_DRAWING_DETECTED", codes)

    def test_comments_and_tracked_changes_detection_preserved(self) -> None:
        tracked_doc = _document_xml().replace("<w:r><w:t>slut</w:t></w:r>", "<w:ins><w:r><w:t>slut</w:t></w:r></w:ins>")
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            _write_docx(docx, document_xml=tracked_doc, include_comments=True, track_revisions=True)
            raw = extract_management_report_raw(docx)
        self.assertTrue(raw["documentFeatures"]["commentsPresent"])
        self.assertTrue(raw["documentFeatures"]["trackedChangesDetected"])
        self.assertTrue(raw["documentFeatures"]["trackRevisionsEnabled"])

    def test_missing_docx_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError):
                extract_management_report_raw(Path(tmp) / "missing.docx")

    def test_corrupt_docx_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.docx"
            bad.write_text("not-zip", encoding="utf-8")
            with self.assertRaises(ExtractionError):
                extract_management_report_raw(bad)

    def test_missing_document_xml_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "bad.docx"
            with zipfile.ZipFile(docx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("word/styles.xml", _styles_xml())
            with self.assertRaises(ExtractionError):
                extract_management_report_raw(docx)

    def test_malformed_document_xml_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "bad.docx"
            with zipfile.ZipFile(docx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("word/document.xml", "<w:document")
            with self.assertRaises(ExtractionError):
                extract_management_report_raw(docx)


if __name__ == "__main__":
    unittest.main()
