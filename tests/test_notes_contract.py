from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notes_contract import (  # noqa: E402
    CANONICAL_NOTE_TITLES,
    NotesContractError,
    build_semantic_notes_contract,
    semantic_notes_contract_json_bytes,
)
from notes_workbook_extractor import raw_notes_workbook_contract_json_bytes  # noqa: E402


def _metadata_file(path: Path, *, company: str = "Omegapoint Malmö AB", org: str = "556613-1339") -> None:
    payload = {
        "companyName": company,
        "organizationNumber": org,
        "reportTitle": "Årsredovisning",
        "reportSubtitle": "Räkenskapsåret",
        "currentReportingPeriod": "2025-01\n-2025-12",
        "previousReportingPeriod": "2024-01\n-2024-12",
        "city": "Malmö",
        "fiscalYear": "2025",
        "documentYear": "2026",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_mapping_payload() -> dict:
    notes = []
    for idx, title in enumerate(CANONICAL_NOTE_TITLES, start=1):
        note_range = f"A{idx}:B{idx}"
        source = {
            "required": True,
            "sourceType": "workbook_range",
            "sheet": "Sheet1",
            "tableShapes": [{"range": note_range, "rowCount": 1, "colCount": 2}],
        }
        authority = "workbook_direct"
        authority_mode = "direct_workbook"
        diagnostics = []
        if idx in (1, 27, 28):
            source = {
                "required": False,
                "sourceType": "management_contract_excluded_content",
                "exclusionKey": "postReportNoteUpdateContent",
            }
            authority = "review_required"
            authority_mode = "full_note_preview_override"
            diagnostics = ["NOTE_TEXT_SOURCE_REQUIRED"]
        notes.append(
            {
                "canonicalOrder": idx,
                "noteNumber": idx,
                "title": title,
                "authorityStatus": authority,
                "authorityMode": authority_mode,
                "diagnosticCodes": diagnostics,
                "source": source,
            }
        )

    return {
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
        "canonicalNotes": notes,
    }


def _mapping_file(path: Path, *, mutate=None) -> None:
    payload = _base_mapping_payload()
    if mutate is not None:
        mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _raw_contract(
    *,
    include_identity_sheet: bool = True,
    identity_company: str = "Omegapoint Malmö AB",
    identity_org: str = "556613-1339",
    mapped_comment_text: str | None = None,
    extra_comments: list[dict] | None = None,
    meaningful_object_on_sheet1: bool = False,
    outside_meaningful_object_sheet: str | None = None,
) -> dict:
    cells = []
    for idx in range(1, 60):
        cells.append(
            {
                "coordinate": f"A{idx}",
                "displayedValue": f"Label {idx}",
                "rawValue": f"Label {idx}",
                "valueType": "string",
                "sourceTrace": {
                    "worksheetName": "Sheet1",
                    "coordinate": f"A{idx}",
                },
            }
        )
        cells.append(
            {
                "coordinate": f"B{idx}",
                "displayedValue": f"Value {idx}",
                "rawValue": f"Value {idx}",
                "valueType": "string",
                "sourceTrace": {
                    "worksheetName": "Sheet1",
                    "coordinate": f"B{idx}",
                },
            }
        )

    # Keep a formula+cached example for formulasUsed and financial-string immutability checks.
    cells.append(
        {
            "coordinate": "B2",
            "displayedValue": "1 234",
            "rawValue": "1 234",
            "valueType": "number",
            "formula": "A2",
            "cachedValue": "1 234",
            "sourceTrace": {
                "worksheetName": "Sheet1",
                "coordinate": "B2",
            },
        }
    )
    cells.append(
        {
            "coordinate": "A3",
            "displayedValue": "2025-01--2025-12",
            "rawValue": "2025-01--2025-12",
            "valueType": "string",
            "sourceTrace": {
                "worksheetName": "Sheet1",
                "coordinate": "A3",
            },
        }
    )

    # Real-workbook-like unrelated org numbers that must remain relatedEntityReferences.
    cells.append(
        {
            "coordinate": "B21",
            "displayedValue": "559313-8166",
            "rawValue": "559313-8166",
            "valueType": "string",
            "sourceTrace": {
                "worksheetName": "Långfristiga värdepappersinneha",
                "coordinate": "B21",
            },
        }
    )
    cells.append(
        {
            "coordinate": "B45",
            "displayedValue": "559313-8166",
            "rawValue": "559313-8166",
            "valueType": "string",
            "sourceTrace": {
                "worksheetName": "Långfristiga värdepappersinneha",
                "coordinate": "B45",
            },
        }
    )
    cells.append(
        {
            "coordinate": "A25",
            "displayedValue": "I enlighet med låneavtal mellan Swedbank och AB Omegapoint, 559312-6120, ansvarar varje borgensman solidariskt.",
            "rawValue": "I enlighet med låneavtal mellan Swedbank och AB Omegapoint, 559312-6120, ansvarar varje borgensman solidariskt.",
            "valueType": "string",
            "sourceTrace": {
                "worksheetName": "Ställda säkerheter och eventual",
                "coordinate": "A25",
            },
        }
    )

    if mapped_comment_text is not None:
        cells.append(
            {
                "coordinate": "A2",
                "displayedValue": "Label 2",
                "rawValue": "Label 2",
                "valueType": "string",
                "commentEvidence": {
                    "commentRef": "A2",
                    "sourcePart": "xl/comments1.xml",
                    "text": mapped_comment_text,
                },
                "sourceTrace": {
                    "worksheetName": "Sheet1",
                    "coordinate": "A2",
                },
            }
        )

    for extra in extra_comments or []:
        sheet = extra.get("sheet", "Sheet1")
        coord = extra.get("coordinate", "C55")
        txt = extra.get("text", "extra comment")
        cells.append(
            {
                "coordinate": coord,
                "displayedValue": extra.get("displayedValue", ""),
                "rawValue": extra.get("rawValue", ""),
                "valueType": "string",
                "commentEvidence": {
                    "commentRef": coord,
                    "sourcePart": extra.get("sourcePart", "xl/comments-extra.xml"),
                    "text": txt,
                },
                "sourceTrace": {
                    "worksheetName": sheet,
                    "coordinate": coord,
                },
            }
        )

    worksheets = [
        {
            "name": "Sheet1",
            "sheetId": 1,
            "visibility": "visible",
            "dimension": "A1:B60",
            "hiddenRows": [],
            "hiddenColumns": [],
            "freezePane": None,
            "mergedRanges": [],
            "dataValidations": [],
            "cells": cells,
            "comments": [],
            "hyperlinks": [],
            "drawingAnchors": [],
        }
    ]

    if include_identity_sheet:
        worksheets.append(
            {
                "name": "Identity",
                "sheetId": 2,
                "visibility": "visible",
                "dimension": "A1:B1",
                "hiddenRows": [],
                "hiddenColumns": [],
                "freezePane": None,
                "mergedRanges": [],
                "dataValidations": [],
                "cells": [
                    {
                        "coordinate": "A1",
                        "displayedValue": identity_company,
                        "rawValue": identity_company,
                        "valueType": "string",
                        "sourceTrace": {
                            "worksheetName": "Identity",
                            "coordinate": "A1",
                        },
                    },
                    {
                        "coordinate": "B1",
                        "displayedValue": identity_org,
                        "rawValue": identity_org,
                        "valueType": "string",
                        "sourceTrace": {
                            "worksheetName": "Identity",
                            "coordinate": "B1",
                        },
                    },
                ],
                "comments": [],
                "hyperlinks": [],
                "drawingAnchors": [],
            }
        )

    diagnostics = [
        {
            "code": "EXTERNAL_LINK_CACHED_VALUE_USED",
            "severity": "review_required",
            "sheet": "Skatt",
            "sourceTrace": "Skatt!F19",
        }
    ]
    if meaningful_object_on_sheet1:
        diagnostics.append(
            {
                "code": "WORKSHEET_DRAWING_RELATIONSHIP_PRESENT",
                "severity": "review_required",
                "sheet": "Sheet1",
                "relationship": {
                    "type": "unsupportedMeaningfulObject",
                    "relationshipId": "rId77",
                    "relationshipType": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
                    "target": "xl/drawings/ole.bin",
                    "targetMode": "",
                },
            }
        )
    if outside_meaningful_object_sheet is not None:
        diagnostics.append(
            {
                "code": "WORKSHEET_DRAWING_RELATIONSHIP_PRESENT",
                "severity": "review_required",
                "sheet": outside_meaningful_object_sheet,
                "relationship": {
                    "type": "unsupportedMeaningfulObject",
                    "relationshipId": "rIdOutside",
                    "relationshipType": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
                    "target": "xl/drawings/outside-ole.bin",
                    "targetMode": "",
                },
            }
        )

    return {
        "schemaVersion": "1.0",
        "source": {"file": "fixture.xlsx", "sha256": "abc"},
        "workbook": {
            "worksheetCount": len(worksheets),
            "sheetOrder": [w["name"] for w in worksheets],
            "nonEmptyCellCount": sum(len(w["cells"]) for w in worksheets),
            "formulaCellCount": 1,
            "authoritativeFormulaMissingCachedCount": 0,
            "externalLinks": {"count": 1, "targets": ["xl/externalLinks/externalLink1.xml"]},
            "calcProperties": {},
        },
        "worksheets": worksheets,
        "diagnostics": diagnostics,
    }


def _management_contract(path: Path, *, placeholder: bool = False) -> None:
    block_28 = "Not X Väsentliga händelser efter räkenskapsårets slut" if placeholder else "Not 28 Väsentliga händelser efter räkenskapsårets slut"
    payload = {
        "excludedContent": [
            {
                "exclusionKey": "postReportNoteUpdateContent",
                "blocks": [
                    {
                        "sourceBlockId": "block-note-1",
                        "text": "Redovisningsprinciper enligt K3 tillämpas.",
                    },
                    {
                        "sourceBlockId": "block-note-27",
                        "text": "Transaktioner med närstående och moderföretag redovisas separat.",
                    },
                    {
                        "sourceBlockId": "block-note-28",
                        "text": block_28,
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class NotesContractTests(unittest.TestCase):
    def test_strict_range_disposition_mode_requires_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["sourceRangeDispositionVersion"] = "1.0"

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("rangeDispositions", str(ctx.exception))

    def test_note4_supporting_range_not_in_render_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            management_raw = tmp_path / "management-report-raw.json"
            management_semantic = tmp_path / "management-report.json"
            notes_raw = tmp_path / "notes-workbook-raw.json"
            notes_semantic = tmp_path / "notes.json"

            mgmt_extract = subprocess.run(
                [
                    "python3",
                    "tools/extract_management_report.py",
                    "--input",
                    "data/mock/management_report_fixture.docx",
                    "--metadata",
                    "data/report_metadata.json",
                    "--raw-output",
                    str(management_raw),
                    "--semantic-output",
                    str(management_semantic),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(mgmt_extract.returncode, 0, msg=mgmt_extract.stderr)

            notes_extract = subprocess.run(
                [
                    "python3",
                    "tools/extract_notes.py",
                    "--input",
                    "data/mock/notes_workbook_fixture.xlsx",
                    "--metadata",
                    "data/report_metadata.json",
                    "--mapping",
                    "data/notes_mapping.json",
                    "--management-contract",
                    str(management_semantic),
                    "--raw-output",
                    str(notes_raw),
                    "--semantic-output",
                    str(notes_semantic),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(notes_extract.returncode, 0, msg=notes_extract.stderr)

            raw = json.loads(notes_raw.read_text(encoding="utf-8"))
            contract = build_semantic_notes_contract(
                raw_contract=raw,
                mapping_path=ROOT / "data" / "notes_mapping.json",
                metadata_path=ROOT / "data" / "report_metadata.json",
                management_contract_path=management_semantic,
            )

            note4 = next(note for note in contract["notes"] if note["noteNumber"] == 4)
            render_ranges = {(item["sheet"], item["range"]) for item in note4["renderTables"]}
            supporting_ranges = {(item["sheet"], item["range"]) for item in note4["supportingEvidence"]}

            self.assertEqual(render_ranges, {("Operationell leasing del 2", "A1:D23")})
            self.assertNotIn(("Operationell leasing del 1", "A1:X172"), render_ranges)
            self.assertEqual(supporting_ranges, {("Operationell leasing del 1", "A1:X172")})

            supporting_item = next(item for item in note4["supportingEvidence"] if item["sheet"] == "Operationell leasing del 1")
            self.assertEqual(supporting_item["disposition"], "supporting_evidence")
            self.assertEqual(supporting_item["reason"], "evidence_not_signed_reference_display_table")

            disposition_item = next(
                item
                for item in note4["sourceRangeDispositions"]
                if item["sheet"] == "Operationell leasing del 1" and item["range"] == "A1:X172"
            )
            self.assertEqual(disposition_item["disposition"], "supporting_evidence")
            self.assertEqual(disposition_item["reason"], "evidence_not_signed_reference_display_table")

    def test_metadata_only_identity_allows_unrelated_org_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            _mapping_file(mapping)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )

            org_evidence = contract["companyIdentityEvidence"]["organizationNumber"]
            self.assertEqual(org_evidence["workbookEvidenceStatus"], "not_present")
            self.assertEqual(org_evidence["validationResult"], "metadata_authoritative")
            self.assertEqual(org_evidence["diagnostic"], "WORKBOOK_REPORTING_ENTITY_ORG_NUMBER_NOT_PRESENT")

    def test_parent_company_org_in_text_is_related_entity_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            _mapping_file(mapping)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )

            refs = contract["companyIdentityEvidence"]["relatedEntityReferences"]
            values = {(r["sheet"], r["coordinate"], r["value"]) for r in refs}
            self.assertIn(("Sheet1", "B21", "559313-8166"), values)
            self.assertIn(("Sheet1", "B45", "559313-8166"), values)
            self.assertIn(("Sheet1", "A25", "559312-6120"), values)

    def test_metadata_only_identity_is_not_reported_as_workbook_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            _mapping_file(mapping)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )

            self.assertNotEqual(contract["companyIdentityEvidence"]["organizationNumber"]["workbookEvidenceStatus"], "match")
            self.assertNotEqual(contract["companyIdentityEvidence"]["companyName"]["workbookEvidenceStatus"], "match")

    def test_configured_org_anchor_exact_match_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["reportingEntityIdentity"]["organizationNumber"] = {
                    "authority": "metadata",
                    "workbookEvidenceMode": "approved_anchor",
                    "workbookAnchor": {"sheet": "Identity", "range": "B1:B1"},
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=True, identity_org="556613-1339"),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )
            org_evidence = contract["companyIdentityEvidence"]["organizationNumber"]
            self.assertEqual(org_evidence["workbookEvidenceStatus"], "match")
            self.assertEqual(org_evidence["validationResult"], "match")

    def test_configured_org_anchor_wrong_value_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["reportingEntityIdentity"]["organizationNumber"] = {
                    "authority": "metadata",
                    "workbookEvidenceMode": "approved_anchor",
                    "workbookAnchor": {"sheet": "Identity", "range": "B1:B1"},
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=True, identity_org="111111-1111"),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("contradicts metadata", str(ctx.exception).lower())

    def test_configured_org_anchor_missing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["reportingEntityIdentity"]["organizationNumber"] = {
                    "authority": "metadata",
                    "workbookEvidenceMode": "approved_anchor",
                    "workbookAnchor": {"sheet": "Identity", "range": "B1:B1"},
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("sheet missing", str(ctx.exception).lower())

    def test_configured_company_anchor_contradiction_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["reportingEntityIdentity"]["companyName"] = {
                    "authority": "metadata",
                    "workbookEvidenceMode": "approved_anchor",
                    "workbookAnchor": {"sheet": "Identity", "range": "A1:A1"},
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=True, identity_company="AB Omegapoint HoldCo"),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("company name", str(ctx.exception).lower())

    def test_duplicate_canonical_note_number_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["canonicalNotes"][1]["noteNumber"] = 1

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError):
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )

    def test_missing_canonical_note_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["canonicalNotes"] = payload["canonicalNotes"][:-1]

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            with self.assertRaises(NotesContractError):
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )

    def test_unexpected_canonical_note_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["canonicalNotes"][27]["noteNumber"] = 29

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            with self.assertRaises(NotesContractError):
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )

    def test_canonical_notes_reordered_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["canonicalNotes"][0], payload["canonicalNotes"][1] = payload["canonicalNotes"][1], payload["canonicalNotes"][0]

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            with self.assertRaises(NotesContractError):
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )

    def test_overlapping_source_range_across_two_notes_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["canonicalNotes"][1]["source"] = {
                    "required": True,
                    "sourceType": "workbook_range",
                    "sheet": "Sheet1",
                    "tableShapes": [{"range": "A2:B2", "rowCount": 1, "colCount": 2}],
                }
                payload["canonicalNotes"][2]["source"] = {
                    "required": True,
                    "sourceType": "workbook_range",
                    "sheet": "Sheet1",
                    "tableShapes": [{"range": "A2:B2", "rowCount": 1, "colCount": 2}],
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("mapped to more than one note", str(ctx.exception).lower())

    def test_exact_source_ranges_and_strings_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            mgmt = p / "management.json"
            _mapping_file(mapping)
            _metadata_file(metadata)
            _management_contract(mgmt)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=mgmt,
            )

            note2 = contract["notes"][1]
            self.assertEqual(note2["sourceReferences"], [{"sheet": "Sheet1", "range": "A2:B2"}])
            self.assertEqual(note2["tables"][0]["rows"][0]["cells"][1]["text"], "1 234")

    def test_raw_contract_sha256_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            _mapping_file(mapping)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                    expected_raw_contract_sha256="deadbeef",
                )
            self.assertIn("sha256", str(ctx.exception).lower())

    def test_management_evidence_mapped_to_notes_1_27_28_with_source_block_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            mgmt = p / "management.json"
            _mapping_file(mapping)
            _metadata_file(metadata)
            _management_contract(mgmt)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=mgmt,
            )

            note1 = contract["notes"][0]
            note27 = contract["notes"][26]
            note28 = contract["notes"][27]
            self.assertEqual(note1["paragraphs"][0]["sourceBlockId"], "block-note-1")
            self.assertEqual(note27["paragraphs"][0]["sourceBlockId"], "block-note-27")
            self.assertEqual(note28["paragraphs"][0]["sourceBlockId"], "block-note-28")

    def test_not_x_remains_verbatim_and_is_diagnosed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            mgmt = p / "management.json"
            _mapping_file(mapping)
            _metadata_file(metadata)
            _management_contract(mgmt, placeholder=True)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=mgmt,
            )

            note28 = contract["notes"][27]
            self.assertIn("Not X", note28["paragraphs"][0]["text"])
            self.assertTrue(note28["paragraphs"][0]["containsNotePlaceholder"])
            self.assertIn("NOTE_NUMBER_PLACEHOLDER_UNRESOLVED", [d["code"] for d in note28["diagnostics"]])

    def test_meaningful_comment_in_mapped_range_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["mappedRangeContentPolicy"] = {
                    "failOnMeaningfulComments": True,
                    "failOnMeaningfulObjects": False,
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False, mapped_comment_text="Meaningful note text"),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("meaningful comment", str(ctx.exception).lower())

    def test_meaningful_object_on_mapped_sheet_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["mappedRangeContentPolicy"] = {
                    "failOnMeaningfulComments": False,
                    "failOnMeaningfulObjects": True,
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False, meaningful_object_on_sheet1=True),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("unknown meaningful object", str(ctx.exception).lower())

    def test_comment_outside_mapped_ranges_is_diagnostic_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            _mapping_file(mapping)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(
                    include_identity_sheet=False,
                    extra_comments=[{"sheet": "Sheet1", "coordinate": "C55", "text": "outside mapped range"}],
                ),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )
            codes = [d.get("code") for d in contract["diagnostics"] if isinstance(d, dict)]
            self.assertIn("UNSUPPORTED_WORKBOOK_COMMENT_OUTSIDE_MAPPED_RANGE", codes)

    def test_allowlisted_known_comment_in_mapped_range_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            known_text = "Known internal comment"

            def mutate(payload: dict) -> None:
                payload["unsupportedContentPolicy"] = {
                    "version": "1.0",
                    "allowlist": [
                        {
                            "id": "mapped-a2",
                            "constructType": "comment",
                            "worksheet": "Sheet1",
                            "coordinate": "A2",
                            "expectedSha256": hashlib.sha256(known_text.encode("utf-8")).hexdigest(),
                            "classification": "internal_instruction",
                            "exclusionReason": "test",
                            "diagnosticCode": "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED",
                            "requiresPresence": True,
                        }
                    ],
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False, mapped_comment_text=known_text),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )
            self.assertIn(
                "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED",
                [d.get("code") for d in contract["diagnostics"] if isinstance(d, dict)],
            )

    def test_allowlisted_comment_changed_text_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["unsupportedContentPolicy"] = {
                    "version": "1.0",
                    "allowlist": [
                        {
                            "id": "mapped-a2",
                            "constructType": "comment",
                            "worksheet": "Sheet1",
                            "coordinate": "A2",
                            "expectedText": "Expected text",
                            "classification": "internal_instruction",
                            "exclusionReason": "test",
                            "diagnosticCode": "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED",
                            "requiresPresence": True,
                        }
                    ],
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            with self.assertRaises(NotesContractError) as ctx:
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False, mapped_comment_text="Changed text"),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )
            self.assertIn("allowlisted comment content changed", str(ctx.exception).lower())

    def test_allowlisted_comment_wrong_coordinate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["unsupportedContentPolicy"] = {
                    "version": "1.0",
                    "allowlist": [
                        {
                            "id": "mapped-a3",
                            "constructType": "comment",
                            "worksheet": "Sheet1",
                            "coordinate": "A3",
                            "expectedText": "Known",
                            "classification": "internal_instruction",
                            "exclusionReason": "test",
                            "diagnosticCode": "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED",
                            "requiresPresence": True,
                        }
                    ],
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)
            with self.assertRaises(NotesContractError):
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(include_identity_sheet=False, mapped_comment_text="Known"),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )

    def test_unknown_second_comment_not_covered_by_allowlist_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            primary = "Known comment"

            def mutate(payload: dict) -> None:
                payload["unsupportedContentPolicy"] = {
                    "version": "1.0",
                    "allowlist": [
                        {
                            "id": "mapped-a2",
                            "constructType": "comment",
                            "worksheet": "Sheet1",
                            "coordinate": "A2",
                            "expectedSha256": hashlib.sha256(primary.encode("utf-8")).hexdigest(),
                            "classification": "internal_instruction",
                            "exclusionReason": "test",
                            "diagnosticCode": "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED",
                            "requiresPresence": True,
                        }
                    ],
                }

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            with self.assertRaises(NotesContractError):
                build_semantic_notes_contract(
                    raw_contract=_raw_contract(
                        include_identity_sheet=False,
                        mapped_comment_text=primary,
                        extra_comments=[{"sheet": "Sheet1", "coordinate": "B2", "text": "unknown second mapped"}],
                    ),
                    mapping_path=mapping,
                    metadata_path=metadata,
                    management_contract_path=None,
                )

    def test_unsupported_artifacts_retain_source_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            _mapping_file(mapping)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(
                    include_identity_sheet=False,
                    extra_comments=[{"sheet": "Sheet1", "coordinate": "C55", "text": "outside comment"}],
                    outside_meaningful_object_sheet="OutsideSheet",
                ),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )

            comment_diag = next(d for d in contract["diagnostics"] if d.get("code") == "UNSUPPORTED_WORKBOOK_COMMENT_OUTSIDE_MAPPED_RANGE")
            self.assertIsInstance(comment_diag.get("sourceTrace"), dict)
            object_diag = next(d for d in contract["diagnostics"] if d.get("code") == "UNSUPPORTED_WORKBOOK_OBJECT_OUTSIDE_MAPPED_RANGE")
            self.assertIsInstance(object_diag.get("relationship"), dict)

    def test_overall_status_is_derived_from_per_note_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"

            def mutate(payload: dict) -> None:
                payload["canonicalNotes"][8]["authorityStatus"] = "blocked"

            _mapping_file(mapping, mutate=mutate)
            _metadata_file(metadata)

            contract = build_semantic_notes_contract(
                raw_contract=_raw_contract(include_identity_sheet=False),
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=None,
            )
            self.assertEqual(contract["status"], "blocked")

    def test_semantic_serialization_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            mapping = p / "mapping.json"
            metadata = p / "metadata.json"
            mgmt = p / "management.json"
            _mapping_file(mapping)
            _metadata_file(metadata)
            _management_contract(mgmt)
            raw = _raw_contract(include_identity_sheet=False)

            contract_a = build_semantic_notes_contract(
                raw_contract=raw,
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=mgmt,
            )
            contract_b = build_semantic_notes_contract(
                raw_contract=raw,
                mapping_path=mapping,
                metadata_path=metadata,
                management_contract_path=mgmt,
            )
            self.assertEqual(semantic_notes_contract_json_bytes(contract_a), semantic_notes_contract_json_bytes(contract_b))
            self.assertEqual(
                contract_a["rawContractSha256"],
                hashlib.sha256(raw_notes_workbook_contract_json_bytes(raw)).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
