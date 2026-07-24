from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from management_report_contract import (
    ContractError,
    _validate_source_block_accounting,
    build_semantic_management_report_contract,
)
from management_report_docx_extractor import extract_management_report_raw


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


def _numbering_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:numbering xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>
"""


def _settings_xml(track_revisions: bool = False) -> str:
    body = "<w:trackRevisions/>" if track_revisions else ""
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:settings xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>
""".replace("/>", ">\n  %s\n</w:settings>" % body)


def _comments_xml(text: str) -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:comments xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:comment w:id='0' w:author='Unit Test'><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:comment>
</w:comments>
""" % text


def _core_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/' xmlns:dcterms='http://purl.org/dc/terms/'>
  <dc:creator>Unit Test</dc:creator>
  <cp:lastModifiedBy>Unit Test</cp:lastModifiedBy>
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
    tr = []
    for row in rows:
        tds = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
        tr.append(f"<w:tr>{tds}</w:tr>")
    return """
    <w:tbl>
      <w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>
      %s
    </w:tbl>
    """ % "".join(tr)


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

    tr = []
    for row in rows:
        tds = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
        tr.append(f"<w:tr>{tds}</w:tr>")

    tr.append("""
      <w:tr>
        <w:tc><w:tcPr><w:gridSpan w:val='6'/></w:tcPr><w:p><w:r><w:t>Förslag till disposition av företagets vinst eller förlust</w:t></w:r></w:p></w:tc>
      </w:tr>
    """)
    tr.append("""
      <w:tr>
        <w:tc><w:tcPr><w:gridSpan w:val='6'/></w:tcPr><w:p><w:r><w:t>Styrelsen föreslår att till förfogande stående vinstmedel, kronor 38 014 289, disponeras enligt följande:</w:t></w:r></w:p></w:tc>
      </w:tr>
    """)
    tr.append("""
      <w:tr>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Belopp i kr</w:t></w:r></w:p></w:tc>
      </w:tr>
    """)
    tr.append("""
      <w:tr>
        <w:tc><w:p><w:r><w:t>Balanseras i ny räkning</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>38 014 289</w:t></w:r></w:p></w:tc>
      </w:tr>
    """)

    return """
    <w:tbl>
      <w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>
      %s
    </w:tbl>
    """ % "".join(tr)


def _base_document_xml() -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body>
    <w:p><w:r><w:t>… = Bolaget uppdaterar texten för ÅR</w:t></w:r></w:p>
    <w:p><w:r><w:t>… = Beskrivning/hjälptext (ska ej ingå i förvaltningsberättelsen eller noten)</w:t></w:r></w:p>
    <w:p><w:r><w:t>Förvaltningsberättelse</w:t></w:r></w:p>
    <w:p><w:r><w:t>Styrelsen och verkställande direktör ... 2025-01-01-2025-12-31.</w:t></w:r></w:p>
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
    <w:p><w:r><w:t>Not X, Väsentliga händelser efter räkenskapsårets slut</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>
""" % (_table1_xml(), _table2_xml())


def _write_docx(
    path: Path,
    *,
    document_xml: str,
    track_revisions: bool = False,
    comments_text: Optional[str] = None,
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", _styles_xml())
        zf.writestr("word/numbering.xml", _numbering_xml())
        zf.writestr("word/settings.xml", _settings_xml(track_revisions=track_revisions))
        zf.writestr("word/_rels/document.xml.rels", _rels_xml())
        zf.writestr("docProps/core.xml", _core_xml())
        if comments_text is not None:
            zf.writestr("word/comments.xml", _comments_xml(comments_text))


def _write_metadata(
    path: Path,
    *,
    current_period: str = "2025-01-01\n-2025-12-31",
    company_name: str = "Omegapoint Malmö AB",
    organization_number: str = "556613-1339",
) -> None:
    payload = {
        "companyName": company_name,
        "organizationNumber": organization_number,
        "reportTitle": "Årsredovisning 2025",
        "reportSubtitle": "PoC",
        "currentReportingPeriod": current_period,
        "previousReportingPeriod": "2024-01-01\n-2024-12-31",
        "city": "Göteborg",
        "fiscalYear": "2025",
        "documentYear": "2026",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ManagementReportContractTests(unittest.TestCase):
    def _build_raw_and_semantic(
        self,
        *,
        doc_xml: Optional[str] = None,
        metadata_current_period: str = "2025-01-01\n-2025-12-31",
        metadata_company_name: str = "Omegapoint Malmö AB",
        metadata_organization_number: str = "556613-1339",
        track_revisions: bool = False,
        comments_text: Optional[str] = None,
    ) -> Tuple[Dict[str, object], Dict[str, object]]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "m.docx"
            metadata = tmp_path / "meta.json"
            _write_docx(
                docx,
                document_xml=doc_xml or _base_document_xml(),
                track_revisions=track_revisions,
                comments_text=comments_text,
            )
            _write_metadata(
                metadata,
                current_period=metadata_current_period,
                company_name=metadata_company_name,
                organization_number=metadata_organization_number,
            )
            raw = extract_management_report_raw(docx)
            semantic = build_semantic_management_report_contract(raw, metadata)
            return raw, semantic

    def _build_contract(
        self,
        *,
        doc_xml: Optional[str] = None,
        metadata_current_period: str = "2025-01-01\n-2025-12-31",
        metadata_company_name: str = "Omegapoint Malmö AB",
        metadata_organization_number: str = "556613-1339",
    ) -> Dict[str, object]:
        _, semantic = self._build_raw_and_semantic(
            doc_xml=doc_xml,
            metadata_current_period=metadata_current_period,
            metadata_company_name=metadata_company_name,
            metadata_organization_number=metadata_organization_number,
        )
        return semantic

    def _doc_with_all_three_alignment_candidates(self) -> str:
        with_office = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Uppsala, Oslo, Köpenhamn och Montréal. Omegapoint är en arbetsplats.</w:t></w:r></w:p>",
            1,
        )
        return with_office.replace(
            "<w:p><w:r><w:t></w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Företagets resultat och ställning i övrigt framgår av efterföljande resultat- och balansräkning samt kassaflödesanalys med noter.</w:t></w:r></w:p>",
            1,
        )

    def test_required_headings_map_to_stable_semantic_keys(self) -> None:
        semantic = self._build_contract()
        keys = [s["sectionKey"] for s in semantic["sections"]]
        self.assertIn("managementReportHeading", keys)
        self.assertIn("businessInformation", keys)
        self.assertIn("equityAndProfitDisposition", keys)

    def test_all_required_sections_present_in_order(self) -> None:
        semantic = self._build_contract()
        self.assertEqual(
            [s["sectionKey"] for s in semantic["sections"]],
            [
                "managementReportHeading",
                "introductoryStatement",
                "currencyStatement",
                "businessInformation",
                "significantEvents",
                "futureDevelopmentAndRisks",
                "researchAndDevelopment",
                "sustainabilityDisclosures",
                "multiYearOverview",
                "equityAndProfitDisposition",
                "closingTransition",
            ],
        )

    def test_exact_word_heading_wording_is_preserved(self) -> None:
        semantic = self._build_contract()
        by_key = {s["sectionKey"]: s for s in semantic["sections"]}
        self.assertEqual(by_key["businessInformation"]["heading"]["text"], "Allmänt om verksamheten")

    def test_sustainability_heading_is_normalized_to_signed_reference_form(self) -> None:
        semantic = self._build_contract()
        by_key = {s["sectionKey"]: s for s in semantic["sections"]}
        self.assertEqual(by_key["sustainabilityDisclosures"]["heading"]["text"], "Hållbarhetsupplysningar")

    def test_business_office_sentence_removes_oslo_when_present_in_source(self) -> None:
        doc = self._doc_with_all_three_alignment_candidates()
        semantic = self._build_contract(doc_xml=doc)
        by_key = {s["sectionKey"]: s for s in semantic["sections"]}
        business_texts = [p["text"] for p in by_key["businessInformation"]["paragraphs"]]
        self.assertTrue(any("Uppsala, Köpenhamn och Montréal." in t for t in business_texts))
        self.assertFalse(any("Uppsala, Oslo, Köpenhamn och Montréal." in t for t in business_texts))

    def test_duplicate_closing_sentence_is_removed_when_present(self) -> None:
        semantic = self._build_contract(doc_xml=self._doc_with_all_three_alignment_candidates())
        by_key = {s["sectionKey"]: s for s in semantic["sections"]}
        closing_texts = [p["text"] for p in by_key["closingTransition"]["paragraphs"]]
        self.assertFalse(any(t.startswith("Vad beträffar resultat och ställning i övrigt") for t in closing_texts))
        self.assertFalse(any(t == "tillhörande noter." for t in closing_texts))

        corrections = {c["correctionId"]: c for c in semantic["signedReferenceCorrections"]}
        self.assertIn("management.closing_sentence_suppression.v1", corrections)
        self.assertEqual(corrections["management.closing_sentence_suppression.v1"]["signedReferencePage"], "4")

    def test_all_three_signed_reference_corrections_persist_pages_scope_and_diagnostics(self) -> None:
        semantic = self._build_contract(doc_xml=self._doc_with_all_three_alignment_candidates())

        corrections = semantic["signedReferenceCorrections"]
        self.assertEqual(len(corrections), 3)
        by_id = {c["correctionId"]: c for c in corrections}

        self.assertEqual(by_id["management.office_location_without_oslo.v1"]["signedReferencePage"], "2")
        self.assertEqual(by_id["management.sustainability_heading_normalization.v1"]["signedReferencePage"], "3")
        self.assertEqual(by_id["management.closing_sentence_suppression.v1"]["signedReferencePage"], "4")

        for record in corrections:
            scope = record["approvalScope"]
            self.assertEqual(scope["scopeId"], "management_alignment_entity_period_section_v1")
            self.assertEqual(scope["companyName"], "Omegapoint Malmö AB")
            self.assertEqual(scope["organizationNumber"], "556613-1339")
            self.assertEqual(scope["currentReportingPeriod"], "2025-01-01\n-2025-12-31")
            self.assertEqual(record["authorityType"], "signed_reference_pdf")

        diagnostics = {d["code"]: d for d in semantic["diagnostics"]}
        self.assertIn("SIGNED_REFERENCE_OFFICE_LOCATION_ALIGNMENT_REQUIRED", diagnostics)
        self.assertIn("SIGNED_REFERENCE_SUSTAINABILITY_HEADING_ALIGNMENT_REQUIRED", diagnostics)
        self.assertIn("SIGNED_REFERENCE_CLOSING_SENTENCE_SUPPRESSION_REQUIRED", diagnostics)

    def test_wrong_entity_fails_closed_for_signed_reference_alignment(self) -> None:
        with self.assertRaises(ContractError):
            self._build_contract(
                doc_xml=self._doc_with_all_three_alignment_candidates(),
                metadata_company_name="Wrong AB",
            )

    def test_wrong_reporting_period_fails_closed_for_signed_reference_alignment(self) -> None:
        with self.assertRaises(ContractError):
            self._build_contract(
                doc_xml=self._doc_with_all_three_alignment_candidates(),
                metadata_current_period="2024-01-01\n-2024-12-31",
            )

    def test_wrong_section_for_office_phrase_fails_closed(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Events paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Uppsala, Oslo, Köpenhamn och Montréal. Omegapoint är en arbetsplats.</w:t></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_changed_office_source_wording_fails_closed(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Uppsala, Oslo, Köpenhamn och Montreal. Omegapoint är en arbetsplats.</w:t></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_multiple_office_phrase_matches_fail_closed(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "".join(
                [
                    "<w:p><w:r><w:t>Uppsala, Oslo, Köpenhamn och Montréal. Omegapoint är en arbetsplats.</w:t></w:r></w:p>",
                    "<w:p><w:r><w:t>Uppsala, Oslo, Köpenhamn och Montréal. Omegapoint är en arbetsplats igen.</w:t></w:r></w:p>",
                ]
            ),
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_closing_suppression_cannot_leave_section_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docx = tmp_path / "m.docx"
            metadata = tmp_path / "meta.json"
            _write_docx(docx, document_xml=self._doc_with_all_three_alignment_candidates())
            _write_metadata(metadata)
            raw = extract_management_report_raw(docx)
            raw["blocks"] = [
                block for block in raw["blocks"]
                if not (block.get("blockType") == "paragraph" and block.get("blockId") == "b0023")
            ]
            with self.assertRaises(ContractError):
                build_semantic_management_report_contract(raw, metadata)

    def test_internal_helper_text_is_explicitly_excluded_with_trace(self) -> None:
        semantic = self._build_contract()
        excluded = {e["exclusionKey"]: e for e in semantic["excludedContent"] if "exclusionKey" in e}
        helper = excluded["internalTemplateInstructions"]
        texts = [b["text"] for b in helper["blocks"]]
        self.assertTrue(any("ska ej ingå i förvaltningsberättelsen eller noten" in t for t in texts))

    def test_post_page_break_note_material_explicitly_excluded_with_trace(self) -> None:
        semantic = self._build_contract()
        excluded = {e["exclusionKey"]: e for e in semantic["excludedContent"] if "exclusionKey" in e}
        post = excluded["postReportNoteUpdateContent"]
        texts = [b["text"] for b in post["blocks"] if b["blockType"] == "paragraph"]
        self.assertTrue(any("NOTER FÖR TEXTUPPDATERING" in t for t in texts))

    def test_ellipsis_without_instruction_phrase_rejected_as_ambiguous(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>… = Bolaget uppdaterar texten för ÅR</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Introduktion … utan instruktion</w:t></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_exclusion_boundary_ambiguity_rejected(self) -> None:
        ambiguous_doc = _base_document_xml().replace("<w:p><w:r><w:br w:type='page'/></w:r></w:p>", "")
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=ambiguous_doc)

    def test_section_order_validated(self) -> None:
        wrong_order = _base_document_xml().replace(
            "<w:p><w:r><w:t>Forskning och utveckling</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Förväntad framtida utveckling samt väsentliga risker och osäkerhetsfaktorer</w:t></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=wrong_order)

    def test_duplicate_heading_rejected(self) -> None:
        duplicate = _base_document_xml().replace(
            "<w:p><w:r><w:t>Allmänt om verksamheten</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Allmänt om verksamheten</w:t></w:r></w:p><w:p><w:r><w:t>Allmänt om verksamheten</w:t></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=duplicate)

    def test_missing_required_heading_rejected(self) -> None:
        missing = _base_document_xml().replace("<w:p><w:r><w:t>Eget kapital</w:t></w:r></w:p>", "")
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=missing)

    def test_required_table1_shape_enforced(self) -> None:
        malformed = _base_document_xml().replace("<w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/>", "<w:gridCol/><w:gridCol/>", 1)
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=malformed)

    def test_required_table2_shape_enforced(self) -> None:
        malformed_table2 = _table2_xml().replace(
            "<w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/>",
            "<w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/><w:gridCol/>",
            1,
        )
        malformed = _base_document_xml().replace(_table2_xml(), malformed_table2, 1)
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=malformed)

    def test_period_matches_metadata_accepted(self) -> None:
        semantic = self._build_contract()
        self.assertEqual(semantic["periodEvidence"]["validationResult"], "match")

    def test_contradictory_period_rejected(self) -> None:
        with self.assertRaises(ContractError):
            self._build_contract(metadata_current_period="2024-01-01\n-2024-12-31")

    def test_semantic_blocks_retain_raw_source_block_ids(self) -> None:
        semantic = self._build_contract()
        all_ids = []
        for section in semantic["sections"]:
            if section["heading"]["sourceBlockId"]:
                all_ids.append(section["heading"]["sourceBlockId"])
            all_ids.extend(p["sourceBlockId"] for p in section["paragraphs"])
        all_ids.extend(t["sourceBlockId"] for t in semantic["tables"])
        for excl in semantic["excludedContent"]:
            all_ids.extend(b["sourceBlockId"] for b in excl["blocks"])
        self.assertTrue(all(isinstance(v, str) and v.startswith("b") for v in all_ids))

    def test_no_raw_source_block_is_silently_lost(self) -> None:
        raw, semantic = self._build_raw_and_semantic()
        raw_ids = {
            b["blockId"]
            for b in raw["blocks"]
            if b["blockType"] in {"paragraph", "table", "explicitPageBreak"}
        }

        used_ids = set()
        for section in semantic["sections"]:
            heading_id = section["heading"]["sourceBlockId"]
            if heading_id:
                used_ids.add(heading_id)
            used_ids.update(p["sourceBlockId"] for p in section["paragraphs"])
        used_ids.update(t["sourceBlockId"] for t in semantic["tables"])
        for excl in semantic["excludedContent"]:
            used_ids.update(b["sourceBlockId"] for b in excl["blocks"])
        for correction in semantic.get("signedReferenceCorrections", []):
            excluded_ids = correction.get("excludedSourceBlockIds", [])
            if isinstance(excluded_ids, list):
                used_ids.update(v for v in excluded_ids if isinstance(v, str))

        self.assertEqual(raw_ids, used_ids)

    def test_source_block_mapped_twice_rejected(self) -> None:
        blocks = [
            {"blockId": "b0001", "blockType": "paragraph", "blockIndex": 1},
        ]
        sections = [
            {
                "sectionKey": "s1",
                "heading": {"sourceBlockId": "b0001", "text": "H"},
                "paragraphs": [],
            }
        ]
        tables = [
            {
                "tableKey": "t1",
                "sourceBlockId": "b0001",
                "table": {},
            }
        ]
        excluded_content: List[Dict[str, object]] = []
        with self.assertRaises(ContractError):
            _validate_source_block_accounting(blocks, sections, tables, excluded_content)

    def test_current_style_table2_produces_review_required_and_authority_diagnostic(self) -> None:
        semantic = self._build_contract()
        self.assertEqual(semantic["status"], "review_required")
        codes = {d["code"] for d in semantic["diagnostics"]}
        self.assertIn("EQUITY_DISPOSITION_SOURCE_AUTHORITY_UNRESOLVED", codes)

    def test_decorative_drawing_and_pict_succeeds_with_semantic_diagnostics(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p><w:p><w:r><w:drawing/></w:r><w:r><w:pict/></w:r></w:p>",
            1,
        )
        semantic = self._build_contract(doc_xml=doc)
        codes = {d["code"] for d in semantic["diagnostics"]}
        self.assertIn("UNSUPPORTED_DECORATIVE_DRAWING_PRESENT", codes)
        self.assertIn("UNSUPPORTED_DECORATIVE_PICT_PRESENT", codes)

    def test_textbox_with_meaningful_text_fails(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:txbxContent><w:p><w:r><w:t>Viktig text i textbox</w:t></w:r></w:p></w:txbxContent></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_field_code_with_meaningful_content_fails(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:instrText>MERGEFIELD IMPORTANT</w:instrText></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_hidden_text_fails(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>hemlig</w:t></w:r></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_contract(doc_xml=doc)

    def test_tracked_changes_with_unrepresented_text_fails(self) -> None:
        doc = _base_document_xml().replace(
            "<w:p><w:r><w:t>Business paragraph.</w:t></w:r></w:p>",
            "<w:p><w:ins><w:r><w:t>Inskjuten text</w:t></w:r></w:ins></w:p>",
            1,
        )
        with self.assertRaises(ContractError):
            self._build_raw_and_semantic(doc_xml=doc, track_revisions=True)

    def test_comments_with_text_fails(self) -> None:
        with self.assertRaises(ContractError):
            self._build_raw_and_semantic(comments_text="Kommentar med text")

    def test_no_word_financial_value_is_altered(self) -> None:
        semantic = self._build_contract()
        table2 = next(t for t in semantic["tables"] if t["tableKey"] == "equityAndProfitDisposition")
        rows = table2["table"]["rows"]
        self.assertEqual(rows[5]["cells"][0]["text"], "Arets resultat")
        self.assertEqual(rows[5]["cells"][5]["text"], "33 324")
        self.assertEqual(rows[10]["cells"][5]["text"], "38 014 289")


if __name__ == "__main__":
    unittest.main()
