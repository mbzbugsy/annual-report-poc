from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notes_contract import CANONICAL_NOTE_TITLES  # noqa: E402
from tests.test_notes_workbook_extractor import _xlsx_fixture  # noqa: E402


def _metadata(path: Path, *, period: str = "2025-01\n-2025-12") -> None:
    payload = {
        "companyName": "Omegapoint Malmö AB",
        "organizationNumber": "556613-1339",
        "reportTitle": "Årsredovisning",
        "reportSubtitle": "Räkenskapsåret",
        "currentReportingPeriod": period,
        "previousReportingPeriod": "2024-01\n-2024-12",
        "city": "Malmö",
        "fiscalYear": "2025",
        "documentYear": "2026",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _full_mapping(path: Path) -> None:
    notes = []
    for idx, title in enumerate(CANONICAL_NOTE_TITLES, start=1):
        note_range = f"A{idx}:B{idx}"
        source = {
            "required": True,
            "sourceType": "workbook_range",
            "sheet": "Sheet1",
            "tableShapes": [{"range": note_range, "rowCount": 1, "colCount": 2}],
        }
        authority_status = "workbook_direct"
        diagnostics = []
        if idx in (1, 27, 28):
            source = {
                "required": False,
                "sourceType": "management_contract_excluded_content",
                "exclusionKey": "postReportNoteUpdateContent",
            }
            authority_status = "review_required"
            diagnostics = ["NOTE_TEXT_SOURCE_REQUIRED"]
        notes.append(
            {
                "canonicalOrder": idx,
                "noteNumber": idx,
                "title": title,
                "authorityStatus": authority_status,
                "diagnosticCodes": diagnostics,
                "source": source,
            }
        )

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
        "canonicalNotes": notes,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _management(path: Path, *, placeholder: bool = False) -> None:
    block28 = "Not X Väsentliga händelser efter räkenskapsårets slut" if placeholder else "Not 28 Väsentliga händelser efter räkenskapsårets slut"
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
                        "text": "Transaktioner med närstående och moderföretag.",
                    },
                    {
                        "sourceBlockId": "block-note-28",
                        "text": block28,
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cmd(
    *,
    workbook: Path,
    metadata: Path,
    mapping: Path,
    raw_output: Path,
    semantic_output: Path,
    management: Path | None,
) -> list[str]:
    command = [
        "python3",
        str(ROOT / "tools" / "extract_notes.py"),
        "--input",
        str(workbook),
        "--metadata",
        str(metadata),
        "--mapping",
        str(mapping),
        "--raw-output",
        str(raw_output),
        "--semantic-output",
        str(semantic_output),
    ]
    if management is not None:
        command.extend(["--management-contract", str(management)])
    return command


class ExtractNotesCliTests(unittest.TestCase):
    def test_cli_success_writes_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "notes.xlsx"
            metadata = tmp_path / "metadata.json"
            mapping = tmp_path / "mapping.json"
            management = tmp_path / "management.json"
            raw_output = tmp_path / "raw.json"
            semantic_output = tmp_path / "semantic.json"

            _xlsx_fixture(workbook, include_comments=False)
            _metadata(metadata)
            _full_mapping(mapping)
            _management(management)

            result = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=management,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(raw_output.exists())
            self.assertTrue(semantic_output.exists())

    def test_cli_failure_leaves_no_partial_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "notes.xlsx"
            metadata = tmp_path / "metadata.json"
            mapping = tmp_path / "mapping.json"
            raw_output = tmp_path / "raw.json"
            semantic_output = tmp_path / "semantic.json"

            _xlsx_fixture(workbook, include_comments=False)
            _metadata(metadata, period="2024-01\n-2024-12")
            _full_mapping(mapping)

            result = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=None,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR:", result.stderr)
            self.assertFalse(raw_output.exists())
            self.assertFalse(semantic_output.exists())

    def test_cli_overwrites_existing_outputs_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "notes.xlsx"
            metadata = tmp_path / "metadata.json"
            mapping = tmp_path / "mapping.json"
            management = tmp_path / "management.json"
            raw_output = tmp_path / "raw.json"
            semantic_output = tmp_path / "semantic.json"

            _xlsx_fixture(workbook, include_comments=False)
            _metadata(metadata)
            _full_mapping(mapping)
            _management(management)
            raw_output.write_text("old", encoding="utf-8")
            semantic_output.write_text("old", encoding="utf-8")

            result = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=management,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(raw_output.read_text(encoding="utf-8").lstrip().startswith("{"))
            self.assertTrue(semantic_output.read_text(encoding="utf-8").lstrip().startswith("{"))
            self.assertEqual(list(tmp_path.glob(".*.tmp")), [])

    def test_failed_rerun_preserves_previous_matching_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "notes.xlsx"
            metadata_ok = tmp_path / "metadata-ok.json"
            metadata_bad = tmp_path / "metadata-bad.json"
            mapping = tmp_path / "mapping.json"
            management = tmp_path / "management.json"
            raw_output = tmp_path / "raw.json"
            semantic_output = tmp_path / "semantic.json"

            _xlsx_fixture(workbook, include_comments=False)
            _metadata(metadata_ok)
            _metadata(metadata_bad, period="2024-01\n-2024-12")
            _full_mapping(mapping)
            _management(management)

            result_ok = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata_ok,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=management,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result_ok.returncode, 0, msg=result_ok.stderr)
            raw_before = raw_output.read_bytes()
            semantic_before = semantic_output.read_bytes()
            raw_before_hash = hashlib.sha256(raw_before).hexdigest()
            semantic_before_hash = hashlib.sha256(semantic_before).hexdigest()

            result_bad = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata_bad,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=management,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result_bad.returncode, 0)
            self.assertIn("ERROR:", result_bad.stderr)

            raw_after = raw_output.read_bytes()
            semantic_after = semantic_output.read_bytes()
            self.assertEqual(hashlib.sha256(raw_after).hexdigest(), raw_before_hash)
            self.assertEqual(hashlib.sha256(semantic_after).hexdigest(), semantic_before_hash)
            self.assertEqual(raw_after, raw_before)
            self.assertEqual(semantic_after, semantic_before)
            self.assertEqual(list(tmp_path.glob(".*.tmp")), [])

    def test_management_contract_omitted_keeps_notes_1_27_28_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "notes.xlsx"
            metadata = tmp_path / "metadata.json"
            mapping = tmp_path / "mapping.json"
            raw_output = tmp_path / "raw.json"
            semantic_output = tmp_path / "semantic.json"

            _xlsx_fixture(workbook, include_comments=False)
            _metadata(metadata)
            _full_mapping(mapping)

            result = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=None,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            semantic = json.loads(semantic_output.read_text(encoding="utf-8"))
            for note_number in (1, 27, 28):
                note = semantic["notes"][note_number - 1]
                self.assertEqual(note["status"], "review_required")
                self.assertIn("NOTE_TEXT_SOURCE_REQUIRED", [d["code"] for d in note["diagnostics"]])

    def test_real_workbook_succeeds_with_exact_allowlisted_artifacts(self) -> None:
        workbook = ROOT / "source-data" / "Not uppgifterna.xlsx"
        metadata = ROOT / "data" / "report_metadata.json"
        mapping = ROOT / "data" / "notes_mapping.json"
        management = ROOT / "generated" / "management-report.json"
        if not workbook.exists() or not management.exists():
            self.skipTest("Local real workbook/management contract not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_output = tmp_path / "raw.json"
            semantic_output = tmp_path / "semantic.json"

            result = subprocess.run(
                _cmd(
                    workbook=workbook,
                    metadata=metadata,
                    mapping=mapping,
                    raw_output=raw_output,
                    semantic_output=semantic_output,
                    management=management,
                ),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            semantic = json.loads(semantic_output.read_text(encoding="utf-8"))
            codes = [d.get("code") for d in semantic.get("diagnostics", []) if isinstance(d, dict)]
            self.assertIn("KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED", codes)
            self.assertEqual(semantic.get("status"), "review_required")


if __name__ == "__main__":
    unittest.main()
