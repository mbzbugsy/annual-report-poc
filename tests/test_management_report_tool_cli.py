from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _styles_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:styles xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:style w:type='paragraph' w:styleId='Normal'><w:name w:val='Normal'/></w:style>
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


def _core_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/' xmlns:dcterms='http://purl.org/dc/terms/'>
  <dc:creator>CLI Test</dc:creator>
  <cp:lastModifiedBy>CLI Test</cp:lastModifiedBy>
  <dcterms:created>2025-03-05T13:49:00Z</dcterms:created>
  <dcterms:modified>2026-03-19T08:46:00Z</dcterms:modified>
</cp:coreProperties>
"""


def _table1_xml() -> str:
    rows = [
        ["Belopp i kkr", "", "", "", "", ""],
        ["", "2025-01-01", "2024-01-01", "2023-01-01", "2022-01-01", "2021-01-01"],
        ["", "2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31"],
        ["Nettoomsättning", "123 537", "129 384", "116 721", "68 682", "54 395"],
        ["Rörelseresultat", "2 262", "4 762", "8 958", "8 552", "8 943"],
        ["Resultat efter skatt", "33", "253", "76", "407", "3 089"],
        ["Rörelsemarginal %", "1,81", "3,7", "7,7", "12,5", "16,4"],
        ["Soliditet%Definitioner: se not xx", "58,8", "60,6", "56,6", "26,9", "25,9"],
    ]
    trs = []
    for row in rows:
        tds = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
        trs.append(f"<w:tr>{tds}</w:tr>")
    return "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>%s</w:tbl>" % "".join(trs)


def _table2_xml() -> str:
    rows = [
        ["", "Aktie-", "Reserv-", "", "Balanserad", "Arets"],
        ["", "kapital", "fond", "", "vinst", "vinst"],
        ["Vid årets början", "120 000", "100 000", "", "37 980 965", "252 733"],
        ["Aktivering av utvecklingskostnader", "", "", "", "-2 308 492", ""],
        ["Omföring av föreg. års vinst", "", "", "", "252 733", "- 252 733"],
        ["Arets resultat", "", "", "", "", "33 324"],
        ["Vid årets slut", "120 000", "100 000", "", "37 980 965", "33 324"],
    ]
    trs = []
    for row in rows:
        tds = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
        trs.append(f"<w:tr>{tds}</w:tr>")
    trs.append("<w:tr><w:tc><w:tcPr><w:gridSpan w:val='6'/></w:tcPr><w:p><w:r><w:t>Förslag till disposition av företagets vinst eller förlust</w:t></w:r></w:p></w:tc></w:tr>")
    trs.append("<w:tr><w:tc><w:tcPr><w:gridSpan w:val='6'/></w:tcPr><w:p><w:r><w:t>Styrelsen föreslår att till förfogande stående vinstmedel, kronor 38 014 289, disponeras enligt följande:</w:t></w:r></w:p></w:tc></w:tr>")
    trs.append("<w:tr><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Belopp i kr</w:t></w:r></w:p></w:tc></w:tr>")
    trs.append("<w:tr><w:tc><w:p><w:r><w:t>Balanseras i ny räkning</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>38 014 289</w:t></w:r></w:p></w:tc></w:tr>")
    return "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>%s</w:tbl>" % "".join(trs)


def _document_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body>
    <w:p><w:r><w:t>… = Bolaget uppdaterar texten för ÅR</w:t></w:r></w:p>
    <w:p><w:r><w:t>… = Beskrivning/hjälptext (ska ej ingå i förvaltningsberättelsen eller noten)</w:t></w:r></w:p>
    <w:p><w:r><w:t>Förvaltningsberättelse</w:t></w:r></w:p>
    <w:p><w:r><w:t>Styrelsen ... 2025-01-01-2025-12-31.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Årsredovisningen är upprättad i svenska kronor, SEK. Om inte annat särskilt anges, redovisas alla</w:t></w:r></w:p>
    <w:p><w:r><w:t>belopp i hela kronor (kr). Uppgifter inom parentes avser föregående år.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Allmänt om verksamheten</w:t></w:r></w:p>
    <w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Utveckling av företagets verksamhet, resultat och ställning</w:t></w:r></w:p>
    %s
    <w:p><w:r><w:t>Väsentliga händelser under räkenskapsåret</w:t></w:r></w:p>
    <w:p><w:r><w:t>Events paragraph.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Forskning och utveckling</w:t></w:r></w:p>
    <w:p><w:r><w:t>R and D paragraph.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Hållbarhetsupplysningar - ESG (Environmental, Social and Governance)</w:t></w:r></w:p>
    <w:p><w:r><w:t>Sustainability paragraph.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Förväntad framtida utveckling samt väsentliga risker och osäkerhetsfaktorer</w:t></w:r></w:p>
    <w:p><w:r><w:t>Future risks paragraph.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Eget kapital</w:t></w:r></w:p>
    %s
    <w:p><w:r><w:t>Vad beträffar resultat och ställning i övrigt hänvisas till efterföljande resultat- och balansräkning med</w:t></w:r></w:p>
    <w:p><w:r><w:t>tillhörande noter.</w:t></w:r></w:p>
    <w:p><w:r><w:br w:type='page'/></w:r></w:p>
    <w:p><w:r><w:t>NOTER FÖR TEXTUPPDATERING</w:t></w:r></w:p>
    <w:p><w:r><w:t>Not X eftertext</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>
""" % (_table1_xml(), _table2_xml())


def _write_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", _document_xml())
        zf.writestr("word/styles.xml", _styles_xml())
        zf.writestr("word/numbering.xml", "<?xml version='1.0' encoding='UTF-8'?><w:numbering xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>")
        zf.writestr("word/settings.xml", "<?xml version='1.0' encoding='UTF-8'?><w:settings xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>")
        zf.writestr("word/_rels/document.xml.rels", _rels_xml())
        zf.writestr("docProps/core.xml", _core_xml())


def _write_metadata(path: Path, *, current_period: str = "2025-01-01\n-2025-12-31") -> None:
    payload = {
        "companyName": "Omegapoint Malmö AB",
        "organizationNumber": "556613-1339",
        "reportTitle": "Årsredovisning 2025",
        "reportSubtitle": "PoC",
        "currentReportingPeriod": current_period,
        "previousReportingPeriod": "2024-01-01\n-2024-12-31",
        "city": "Göteborg",
        "fiscalYear": "2025",
        "documentYear": "2026",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ManagementReportCliTests(unittest.TestCase):
    def _run_cli(self, input_docx: Path, metadata: Path, raw_output: Path, semantic_output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                "tools/extract_management_report.py",
                "--input",
                str(input_docx),
                "--metadata",
                str(metadata),
                "--raw-output",
                str(raw_output),
                "--semantic-output",
                str(semantic_output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_successful_cli_writes_both_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "source.docx"
            meta = tmp_path / "meta.json"
            raw = tmp_path / "out" / "raw.json"
            semantic = tmp_path / "out" / "semantic.json"
            _write_docx(docx)
            _write_metadata(meta)

            result = self._run_cli(docx, meta, raw, semantic)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(raw.exists())
            self.assertTrue(semantic.exists())

    def test_output_is_deterministic_across_two_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "source.docx"
            meta = tmp_path / "meta.json"
            raw = tmp_path / "out" / "raw.json"
            semantic = tmp_path / "out" / "semantic.json"
            _write_docx(docx)
            _write_metadata(meta)

            first = self._run_cli(docx, meta, raw, semantic)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            h1_raw = hashlib.sha256(raw.read_bytes()).hexdigest()
            h1_sem = hashlib.sha256(semantic.read_bytes()).hexdigest()

            second = self._run_cli(docx, meta, raw, semantic)
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            h2_raw = hashlib.sha256(raw.read_bytes()).hexdigest()
            h2_sem = hashlib.sha256(semantic.read_bytes()).hexdigest()

        self.assertEqual(h1_raw, h2_raw)
        self.assertEqual(h1_sem, h2_sem)

    def test_missing_input_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            missing = tmp_path / "missing.docx"
            meta = tmp_path / "meta.json"
            raw = tmp_path / "raw.json"
            semantic = tmp_path / "semantic.json"
            _write_metadata(meta)
            result = self._run_cli(missing, meta, raw, semantic)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR:", result.stderr)

    def test_corrupt_input_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "bad.docx"
            meta = tmp_path / "meta.json"
            raw = tmp_path / "raw.json"
            semantic = tmp_path / "semantic.json"
            docx.write_text("not-zip", encoding="utf-8")
            _write_metadata(meta)
            result = self._run_cli(docx, meta, raw, semantic)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR:", result.stderr)

    def test_failure_does_not_leave_partial_semantic_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "source.docx"
            meta = tmp_path / "meta.json"
            raw = tmp_path / "out" / "raw.json"
            semantic = tmp_path / "out" / "semantic.json"
            _write_docx(docx)
            _write_metadata(meta, current_period="2024-01-01\n-2024-12-31")

            result = self._run_cli(docx, meta, raw, semantic)

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(raw.exists())
            self.assertFalse(semantic.exists())

    def test_failed_rerun_preserves_previous_matching_raw_and_semantic_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "source.docx"
            meta_ok = tmp_path / "meta-ok.json"
            meta_bad = tmp_path / "meta-bad.json"
            out_dir = tmp_path / "out"
            raw = out_dir / "raw.json"
            semantic = out_dir / "semantic.json"
            _write_docx(docx)
            _write_metadata(meta_ok, current_period="2025-01-01\n-2025-12-31")
            _write_metadata(meta_bad, current_period="2024-01-01\n-2024-12-31")

            ok_result = self._run_cli(docx, meta_ok, raw, semantic)
            self.assertEqual(ok_result.returncode, 0, msg=ok_result.stderr)
            raw_before = raw.read_bytes()
            semantic_before = semantic.read_bytes()

            bad_result = self._run_cli(docx, meta_bad, raw, semantic)
            self.assertNotEqual(bad_result.returncode, 0)

            self.assertEqual(raw_before, raw.read_bytes())
            self.assertEqual(semantic_before, semantic.read_bytes())

            staged_leftovers = list(out_dir.glob(".*.tmp"))
            self.assertEqual(staged_leftovers, [])

    def test_parent_directories_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "source.docx"
            meta = tmp_path / "meta.json"
            raw = tmp_path / "nested" / "a" / "raw.json"
            semantic = tmp_path / "nested" / "b" / "semantic.json"
            _write_docx(docx)
            _write_metadata(meta)

            result = self._run_cli(docx, meta, raw, semantic)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(raw.exists())
            self.assertTrue(semantic.exists())


if __name__ == "__main__":
    unittest.main()
