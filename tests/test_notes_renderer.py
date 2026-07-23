from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notes_renderer import NotesRenderError, _display_from_cell  # noqa: E402
from notes_provenance import NotesProvenanceError, validate_provenance_payload  # noqa: E402


class NotesRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._tmp_path = Path(cls._tmpdir.name)
        cls.raw_path = cls._tmp_path / "notes-workbook-raw.json"
        cls.semantic_path = cls._tmp_path / "notes.json"
        cls.management_path = cls._tmp_path / "management-report.json"

        mgmt_extract = subprocess.run(
            [
                "python3",
                "tools/extract_management_report.py",
                "--input",
                "data/mock/management_report_fixture.docx",
                "--metadata",
                "data/report_metadata.json",
                "--raw-output",
                str(cls._tmp_path / "management-report-raw.json"),
                "--semantic-output",
                str(cls.management_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if mgmt_extract.returncode != 0:
            raise AssertionError(f"Management fixture extraction failed: {mgmt_extract.stderr}")

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
                str(cls.management_path),
                "--raw-output",
                str(cls.raw_path),
                "--semantic-output",
                str(cls.semantic_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if notes_extract.returncode != 0:
            raise AssertionError(f"Notes fixture extraction failed: {notes_extract.stderr}")

        cls.base_override = json.loads((ROOT / "data/mock/notes_preview_overrides.json").read_text(encoding="utf-8"))
        cls.base_semantic = json.loads(cls.semantic_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def _sync_raw_hash(self, semantic_payload: dict[str, object], raw_payload: dict[str, object]) -> None:
        payload_bytes = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        semantic_payload["rawContractSha256"] = hashlib.sha256(payload_bytes).hexdigest()

    def _set_cell_fields(
        self,
        semantic_payload: dict[str, object],
        *,
        note_number: int,
        coordinate: str,
        fields: dict[str, object],
    ) -> None:
        notes = semantic_payload.get("notes")
        if not isinstance(notes, list):
            self.fail("semantic payload notes missing")

        touched = 0
        for note in notes:
            if not isinstance(note, dict) or note.get("noteNumber") != note_number:
                continue
            for key in ("tables", "renderTables"):
                tables = note.get(key)
                if not isinstance(tables, list):
                    continue
                for table in tables:
                    if not isinstance(table, dict):
                        continue
                    rows = table.get("rows")
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        cells = row.get("cells")
                        if not isinstance(cells, list):
                            continue
                        for cell in cells:
                            if not isinstance(cell, dict):
                                continue
                            if cell.get("coordinate") == coordinate:
                                cell.update(fields)
                                touched += 1
        if touched == 0:
            self.fail(f"coordinate not found in note {note_number}: {coordinate}")

    def _run_render(
        self,
        *,
        semantic_payload: dict[str, object] | None = None,
        raw_payload: dict[str, object] | None = None,
        override_payload: dict[str, object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            semantic_path = tmp_path / "notes.json"
            raw_path = tmp_path / "notes-workbook-raw.json"
            override_path = tmp_path / "override.json"
            output_path = tmp_path / "notes.tex"
            provenance_path = tmp_path / "notes.provenance.json"

            if semantic_payload is None:
                semantic_path.write_text(self.semantic_path.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                semantic_path.write_text(json.dumps(semantic_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            if raw_payload is None:
                raw_path.write_text(self.raw_path.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            payload = override_payload if override_payload is not None else deepcopy(self.base_override)
            override_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    "tools/render_notes_tex.py",
                    "--semantic-input",
                    str(semantic_path),
                    "--raw-input",
                    str(raw_path),
                    "--metadata",
                    "data/report_metadata.json",
                    "--mapping",
                    "data/notes_mapping.json",
                    "--management-contract",
                    str(self.management_path),
                    "--override",
                    str(override_path),
                    "--output",
                    str(output_path),
                    "--provenance-output",
                    str(provenance_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            result.output_exists = output_path.exists()
            result.provenance_exists = provenance_path.exists()
            result.output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            result.provenance_payload = (
                json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else None
            )
            return result

    def test_authority_modes_are_exact_approved_sets(self) -> None:
        notes = self.base_semantic["notes"]
        direct = {n["noteNumber"] for n in notes if n["renderAuthority"]["mode"] == "direct_workbook"}
        hybrid = {n["noteNumber"] for n in notes if n["renderAuthority"]["mode"] == "hybrid_workbook_preview_override"}
        full = {n["noteNumber"] for n in notes if n["renderAuthority"]["mode"] == "full_note_preview_override"}

        self.assertEqual(direct, {4, 13, 14})
        self.assertEqual(hybrid, {17, 18, 19, 22, 23, 26})
        self.assertEqual(full, {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 20, 21, 24, 25, 27, 28})

    def test_override_manifest_has_required_sections(self) -> None:
        override = self.base_override
        self.assertIn("fullNoteOverrides", override)
        self.assertIn("fieldOverrides", override)
        self.assertIn("rowOverrides", override)
        self.assertIn("labelMappings", override)
        self.assertIn("acknowledgedPolicyDiagnostics", override)

        full = {n["noteNumber"] for n in override["fullNoteOverrides"]}
        self.assertEqual(full, {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 20, 21, 24, 25, 27, 28})

    def test_valid_inputs_render_notes_tex_and_provenance(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(result.output_exists)
        self.assertTrue(result.provenance_exists)

        tex = result.output_text
        for page in range(9, 20):
            self.assertIn(f"{page} (19)", tex)
        self.assertIn("Not 1 Redovisnings- och värderingsprinciper", tex)
        self.assertIn("Not 28 Väsentliga händelser efter räkenskapsårets slut", tex)

        prov = result.provenance_payload
        assert prov is not None
        self.assertEqual(prov["schemaVersion"], "2.0")
        self.assertIn("notes", prov)

    def test_provenance_distinguishes_three_authority_modes(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prov = result.provenance_payload
        assert prov is not None

        notes = prov["notes"]
        direct = {int(k) for k, v in notes.items() if v["renderAuthority"] == "direct_workbook"}
        hybrid = {int(k) for k, v in notes.items() if v["renderAuthority"] == "hybrid_workbook_preview_override"}
        full = {int(k) for k, v in notes.items() if v["renderAuthority"] == "full_note_preview_override"}

        self.assertEqual(direct, {4, 13, 14})
        self.assertEqual(hybrid, {17, 18, 19, 22, 23, 26})
        self.assertEqual(full, {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 20, 21, 24, 25, 27, 28})

    def test_note4_supporting_range_not_rendered(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prov = result.provenance_payload
        assert prov is not None

        note4 = prov["rangeDispositionAccounting"]["4"]
        self.assertEqual(note4["renderedSourceRanges"], ["Operationell leasing del 2:A1:D23"])
        self.assertEqual(note4["supportingEvidenceRanges"], ["Operationell leasing del 1:A1:X172"])

    def test_hybrid_workbook_cells_appear_once(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prov = result.provenance_payload
        assert prov is not None
        for note in [17, 18, 19, 22, 23, 26]:
            cells = prov["notes"][str(note)]["workbookRenderedSourceCells"]
            self.assertEqual(len(cells), len(set(cells)))

    def test_broad_blank_to_zero_policy_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["overrideKind"] = "broad blank-to-zero"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_broad_rounding_tolerance_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["overrideKind"] = "broad rounding tolerance"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_override_kind_allowlist_accepts_all_committed_kinds(self) -> None:
        field_kinds = {item["overrideKind"] for item in self.base_override["fieldOverrides"]}
        row_kinds = {item["overrideKind"] for item in self.base_override["rowOverrides"]}
        label_kinds = {item["overrideKind"] for item in self.base_override["labelMappings"]}

        self.assertEqual(field_kinds, {"blank-to-zero presentation", "signed-preview value override"})
        self.assertEqual(row_kinds, {"display formatting", "row-role authority", "signed-preview value override"})
        self.assertEqual(label_kinds, {"label mapping"})

        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_unknown_override_kind_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["overrideKind"] = "unapproved-kind"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_missing_override_kind_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0].pop("overrideKind", None)
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overrideKind", result.stderr)

    def test_broad_blank_to_zero_spelling_variant_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["overrideKind"] = "blank to zero presentation"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_broad_blank_to_zero_snake_case_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["overrideKind"] = "broad_blank_to_zero"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_override_kind_different_casing_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["overrideKind"] = "Blank-to-zero presentation"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_valid_override_with_unapproved_kind_is_rejected(self) -> None:
        override = deepcopy(self.base_override)
        row = next(item for item in override["rowOverrides"] if item["type"] == "workbook_row_authority")
        row["overrideKind"] = "section-wide authority"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported overrideKind", result.stderr)

    def test_diagnostic_covered_absent_code_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["fieldOverrides"][0]["diagnosticCovered"] = "NOT_A_REAL_DIAGNOSTIC"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("claims absent diagnostic", result.stderr)

    def test_diagnostic_covered_correct_code_wrong_note_rejected(self) -> None:
        override = deepcopy(self.base_override)
        target = next(item for item in override["labelMappings"] if item["noteNumber"] == 18)
        target["diagnosticCovered"] = "BLANK_TO_ZERO_PRESENTATION_REQUIRED"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("claims absent diagnostic", result.stderr)

    def test_diagnostic_covered_global_code_claimed_note_local_rejected(self) -> None:
        override = deepcopy(self.base_override)
        target = next(item for item in override["fieldOverrides"] if item["noteNumber"] == 17)
        target["diagnosticCovered"] = "GLOBAL_ONLY_REVIEW_DIAGNOSTIC"

        semantic = deepcopy(self.base_semantic)
        semantic.setdefault("diagnostics", []).append(
            {
                "code": "GLOBAL_ONLY_REVIEW_DIAGNOSTIC",
                "severity": "review_required",
                "message": "test",
            }
        )

        result = self._run_render(override_payload=override, semantic_payload=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("claims global diagnostic as note-local", result.stderr)

    def test_diagnostic_covered_empty_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["rowOverrides"][0]["diagnosticCovered"] = ""
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("diagnosticCovered", result.stderr)

    def test_note_local_diagnostic_claimed_globally_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["acknowledgedPolicyDiagnostics"].append(
            {
                "code": "ROW_ROLE_AUTHORITY_REQUIRED",
                "noteNumber": None,
                "sourceRef": "test",
            }
        )
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Override claims absent diagnostics", result.stderr)

    def test_signed_reference_page_unknown_rejected(self) -> None:
        override = deepcopy(self.base_override)
        note2 = next(item for item in override["fullNoteOverrides"] if item["noteNumber"] == 2)
        note2["coveredSourceRefs"][0]["value"] = "unknown"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be numeric page reference", result.stderr)

    def test_signed_reference_page_non_numeric_rejected(self) -> None:
        override = deepcopy(self.base_override)
        note2 = next(item for item in override["fullNoteOverrides"] if item["noteNumber"] == 2)
        note2["coveredSourceRefs"][0]["value"] = "page11"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be numeric page reference", result.stderr)

    def test_signed_reference_page_missing_rejected(self) -> None:
        override = deepcopy(self.base_override)
        note2 = next(item for item in override["fullNoteOverrides"] if item["noteNumber"] == 2)
        note2["coveredSourceRefs"] = []
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("coveredSourceRefs must be non-empty list", result.stderr)

    def test_note2_and_note3_signed_reference_pages_are_fixed(self) -> None:
        note2 = next(item for item in self.base_override["fullNoteOverrides"] if item["noteNumber"] == 2)
        note3 = next(item for item in self.base_override["fullNoteOverrides"] if item["noteNumber"] == 3)
        self.assertEqual(note2["coveredSourceRefs"], [{"kind": "signed_reference_page", "value": "11"}])
        self.assertEqual(note3["coveredSourceRefs"], [{"kind": "signed_reference_page", "value": "12"}])

    def test_missing_hybrid_source_cell_fails(self) -> None:
        override = deepcopy(self.base_override)
        target = next(item for item in override["rowOverrides"] if item["noteNumber"] == 17 and item["type"] == "workbook_row_authority")
        target["currentCell"] = "ZZ999"
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing hybrid source cell", result.stderr)

    def test_full_note_override_cannot_be_empty(self) -> None:
        override = deepcopy(self.base_override)
        n2 = next(item for item in override["fullNoteOverrides"] if item["noteNumber"] == 2)
        n2["paragraphs"] = []
        n2["tables"] = []
        n2.pop("pageSegments", None)
        result = self._run_render(override_payload=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing visible signed-reference block", result.stderr)

    def test_unresolved_direct_note_fails(self) -> None:
        semantic = deepcopy(self.base_semantic)
        note4 = next(n for n in semantic["notes"] if n["noteNumber"] == 4)
        note4["diagnostics"] = [{"code": "UNRESOLVED_DIRECT", "severity": "review_required"}]
        result = self._run_render(semantic_payload=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("direct mode", result.stderr)

    def test_pagination_derived_split_mismatch_fails_accounting(self) -> None:
        semantic = deepcopy(self.base_semantic)
        note17 = next(n for n in semantic["notes"] if n["noteNumber"] == 17)
        note17["sourceRangeDispositions"] = [
            {
                "sheet": "Övriga kf fordringar",
                "range": "A1:M14",
                "disposition": "render_content",
                "expectedRowCount": 14,
                "expectedColCount": 13,
            },
            {
                "sheet": "Övriga kf fordringar",
                "range": "A15:M44",
                "disposition": "supporting_evidence",
                "expectedRowCount": 30,
                "expectedColCount": 13,
            },
        ]
        result = self._run_render(semantic_payload=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unmapped range", result.stderr)

    def test_full_override_notes_do_not_mix_workbook_rows(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        prov = result.provenance_payload
        assert prov is not None
        for note in [1, 2, 3, 5, 10, 11, 12, 15, 16, 20, 21, 24, 25, 27, 28, 6, 7, 8, 9]:
            item = prov["notes"][str(note)]
            self.assertTrue(item["fullNoteOverrideUsed"])
            self.assertEqual(item["workbookRenderedSourceCells"], [])

    def test_tex_and_provenance_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "notes.tex"
            provenance_path = tmp_path / "notes.provenance.json"

            cmd = [
                "python3",
                "tools/render_notes_tex.py",
                "--semantic-input",
                str(self.semantic_path),
                "--raw-input",
                str(self.raw_path),
                "--metadata",
                "data/report_metadata.json",
                "--mapping",
                "data/notes_mapping.json",
                "--management-contract",
                str(self.management_path),
                "--override",
                "data/mock/notes_preview_overrides.json",
                "--output",
                str(output_path),
                "--provenance-output",
                str(provenance_path),
            ]

            first = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            first_tex_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            first_prov_hash = hashlib.sha256(provenance_path.read_bytes()).hexdigest()

            second = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            second_tex_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            second_prov_hash = hashlib.sha256(provenance_path.read_bytes()).hexdigest()

            self.assertEqual(first_tex_hash, second_tex_hash)
            self.assertEqual(first_prov_hash, second_prov_hash)

    def test_note13_known_serials_render_expected_dates(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Belopp i SEK &  &  & 2025-12-31 &  & 2024-12-31", result.output_text)

    def test_excel_1904_date_system_changes_numeric_date_conversion(self) -> None:
        semantic = deepcopy(self.base_semantic)
        raw = json.loads(self.raw_path.read_text(encoding="utf-8"))
        raw["workbook"]["dateSystem"] = {
            "mode": "excel_1904",
            "source": "test",
        }
        self._sync_raw_hash(semantic, raw)
        result = self._run_render(semantic_payload=semantic, raw_payload=raw)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Belopp i SEK &  &  & 2030-01-01 &  & 2029-01-01", result.output_text)

    def test_missing_date_system_evidence_fails_closed_for_numeric_date_cells(self) -> None:
        semantic = deepcopy(self.base_semantic)
        raw = json.loads(self.raw_path.read_text(encoding="utf-8"))
        raw.get("workbook", {}).pop("dateSystem", None)
        self._sync_raw_hash(semantic, raw)
        result = self._run_render(semantic_payload=semantic, raw_payload=raw)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing workbook date-system evidence", result.stderr)

    def test_unsupported_numeric_date_format_fails_closed(self) -> None:
        semantic = deepcopy(self.base_semantic)
        self._set_cell_fields(
            semantic,
            note_number=13,
            coordinate="D3",
            fields={"numberFormat": "yyyy-mm", "rawValue": "46022", "text": "46022", "displayedValue": "46022"},
        )
        result = self._run_render(semantic_payload=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported numeric date format", result.stderr)

    def test_quoted_yyyy_literal_is_not_detected_as_date_format(self) -> None:
        with self.assertRaises(NotesRenderError) as ctx:
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": '"yyyy"',
                    "rawValue": "46022",
                    "text": "46022",
                    "displayedValue": "46022",
                },
                workbook_date_system="excel_1900",
            )
        self.assertIn("Unsupported workbook number format", str(ctx.exception))

    def test_supported_custom_date_format_is_deterministic(self) -> None:
        cell = {
            "coordinate": "A1",
            "numberFormat": "yyyy\\-mm\\-dd",
            "rawValue": "46022",
            "text": "46022",
            "displayedValue": "46022",
        }
        first = _display_from_cell(cell, workbook_date_system="excel_1900")
        second = _display_from_cell(cell, workbook_date_system="excel_1900")
        self.assertEqual(first, "2025-12-31")
        self.assertEqual(first, second)

    def test_excel_1900_serial_1_rejected(self) -> None:
        with self.assertRaises(NotesRenderError) as ctx:
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "builtin:14",
                    "rawValue": "1",
                    "text": "1",
                    "displayedValue": "1",
                },
                workbook_date_system="excel_1900",
            )
        self.assertIn("fictitious 1900 leap-day behavior", str(ctx.exception))

    def test_excel_1900_serial_59_rejected(self) -> None:
        with self.assertRaises(NotesRenderError):
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "builtin:14",
                    "rawValue": "59",
                    "text": "59",
                    "displayedValue": "59",
                },
                workbook_date_system="excel_1900",
            )

    def test_excel_1900_serial_60_rejected(self) -> None:
        with self.assertRaises(NotesRenderError):
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "builtin:14",
                    "rawValue": "60",
                    "text": "60",
                    "displayedValue": "60",
                },
                workbook_date_system="excel_1900",
            )

    def test_excel_1900_serial_61_is_supported(self) -> None:
        rendered = _display_from_cell(
            {
                "coordinate": "A1",
                "numberFormat": "builtin:14",
                "rawValue": "61",
                "text": "61",
                "displayedValue": "61",
            },
            workbook_date_system="excel_1900",
        )
        self.assertEqual(rendered, "1900-03-01")

    def test_excel_1904_serial_conversion_unchanged(self) -> None:
        rendered = _display_from_cell(
            {
                "coordinate": "A1",
                "numberFormat": "builtin:14",
                "rawValue": "1",
                "text": "1",
                "displayedValue": "1",
            },
            workbook_date_system="excel_1904",
        )
        self.assertEqual(rendered, "1904-01-02")

    def test_unsupported_numeric_general_format_fails_closed(self) -> None:
        with self.assertRaises(NotesRenderError) as ctx:
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "builtin:0",
                    "rawValue": "1234.5",
                    "text": "1234.5",
                    "displayedValue": "1234.5",
                },
                workbook_date_system="excel_1900",
            )
        self.assertIn("Unsupported numeric General-format value", str(ctx.exception))

    def test_text_general_value_passes_through(self) -> None:
        rendered = _display_from_cell(
            {
                "coordinate": "A1",
                "numberFormat": "builtin:0",
                "rawValue": "AB12",
                "text": "AB12",
                "displayedValue": "AB12",
            },
            workbook_date_system="excel_1900",
        )
        self.assertEqual(rendered, "AB12")

    def test_formula_date_cell_uses_cached_raw_value_without_recalculation(self) -> None:
        rendered = _display_from_cell(
            {
                "coordinate": "A1",
                "numberFormat": "builtin:14",
                "rawValue": "46022",
                "cachedValue": "46022",
                "formula": "1+1",
                "text": "46022",
                "displayedValue": "46022",
            },
            workbook_date_system="excel_1900",
        )
        self.assertEqual(rendered, "2025-12-31")

    def test_blank_numeric_value_stays_blank(self) -> None:
        rendered = _display_from_cell(
            {
                "coordinate": "A1",
                "numberFormat": "builtin:3",
                "rawValue": "",
                "text": "",
                "displayedValue": "",
            },
            workbook_date_system="excel_1900",
        )
        self.assertEqual(rendered, "")

    def test_full_note_override_date_strings_are_not_reformatted(self) -> None:
        override = deepcopy(self.base_override)
        note2 = next(item for item in override["fullNoteOverrides"] if item["noteNumber"] == 2)
        note2["paragraphs"] = ["Bevarad datumsträng 2025-12-31 exakt."]
        result = self._run_render(override_payload=override)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Bevarad datumsträng 2025-12-31 exakt.", result.output_text)

    def test_hybrid_field_override_values_are_not_reformatted(self) -> None:
        override = deepcopy(self.base_override)
        target = next(item for item in override["fieldOverrides"] if item["noteNumber"] == 17)
        target["signedDisplayValue"] = "2025-12-31"
        result = self._run_render(override_payload=override)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("2025-12-31", result.output_text)

    def test_swedish_integer_decimal_and_percentage_formatting(self) -> None:
        self.assertEqual(
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "builtin:3",
                    "rawValue": "1234567",
                    "text": "1234567",
                    "displayedValue": "1234567",
                },
                workbook_date_system="excel_1900",
            ),
            "1 234 567",
        )
        self.assertEqual(
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "builtin:2",
                    "rawValue": "1234.5",
                    "text": "1234.5",
                    "displayedValue": "1234.5",
                },
                workbook_date_system="excel_1900",
            ),
            "1 234,50",
        )
        self.assertEqual(
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "0.0%",
                    "rawValue": "0.125",
                    "text": "0.125",
                    "displayedValue": "0.125",
                },
                workbook_date_system="excel_1900",
            ),
            "12,5 %",
        )

    def test_unknown_numeric_format_fails_closed(self) -> None:
        with self.assertRaises(NotesRenderError) as ctx:
            _display_from_cell(
                {
                    "coordinate": "A1",
                    "numberFormat": "0.0000",
                    "rawValue": "1.2345",
                    "text": "1.2345",
                    "displayedValue": "1.2345",
                },
                workbook_date_system="excel_1900",
            )
        self.assertIn("Unsupported workbook number format", str(ctx.exception))

    def test_provenance_validation_accepts_valid_payload(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        assert result.provenance_payload is not None
        validate_provenance_payload(result.provenance_payload)

    def test_provenance_validation_rejects_missing_required_top_level_field(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        provenance = deepcopy(result.provenance_payload)
        assert provenance is not None
        provenance.pop("previewOverrideSourceType")
        with self.assertRaises(NotesProvenanceError):
            validate_provenance_payload(provenance)

    def test_provenance_validation_rejects_missing_note_key(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        provenance = deepcopy(result.provenance_payload)
        assert provenance is not None
        provenance["notes"].pop("28")
        with self.assertRaises(NotesProvenanceError):
            validate_provenance_payload(provenance)

    def test_provenance_validation_rejects_authority_matrix_corruption(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        provenance = deepcopy(result.provenance_payload)
        assert provenance is not None
        provenance["notes"]["4"]["renderAuthority"] = "full_note_preview_override"
        with self.assertRaises(NotesProvenanceError):
            validate_provenance_payload(provenance)

    def test_provenance_validation_rejects_mode_specific_inconsistency(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        provenance = deepcopy(result.provenance_payload)
        assert provenance is not None
        provenance["notes"]["1"]["fullNoteOverrideUsed"] = False
        with self.assertRaises(NotesProvenanceError):
            validate_provenance_payload(provenance)

    def test_provenance_validation_rejects_missing_physical_page(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        provenance = deepcopy(result.provenance_payload)
        assert provenance is not None
        provenance["notes"]["17"].pop("physicalPage")
        with self.assertRaises(NotesProvenanceError):
            validate_provenance_payload(provenance)


if __name__ == "__main__":
    unittest.main()
