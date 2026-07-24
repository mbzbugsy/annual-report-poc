from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ManagementReportRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._tmp_path = Path(cls._tmpdir.name)
        cls.semantic_path = cls._tmp_path / "semantic.json"
        cls.raw_path = cls._tmp_path / "raw.json"

        extract = subprocess.run(
            [
                "python3",
                "tools/extract_management_report.py",
                "--input",
                "data/mock/management_report_fixture.docx",
                "--metadata",
                "data/report_metadata.json",
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
        if extract.returncode != 0:
            raise AssertionError(f"Fixture extraction failed: {extract.stderr}")

        cls.base_semantic = json.loads(cls.semantic_path.read_text(encoding="utf-8"))
        cls.base_raw = json.loads(cls.raw_path.read_text(encoding="utf-8"))
        cls.base_override = json.loads(
            (ROOT / "data/mock/management_report_page4_preview_override.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def _run_render(
        self,
        *,
        semantic: dict[str, object] | None = None,
        raw: dict[str, object] | None = None,
        override: dict[str, object] | None = None,
        metadata_payload: dict[str, object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            semantic_path = tmp_path / "semantic.json"
            raw_path = tmp_path / "raw.json"
            override_path = tmp_path / "override.json"
            metadata_path = tmp_path / "metadata.json"
            output_path = tmp_path / "management-report.tex"
            provenance_path = tmp_path / "management-report.provenance.json"

            semantic_payload = semantic if semantic is not None else deepcopy(self.base_semantic)
            raw_payload = raw if raw is not None else deepcopy(self.base_raw)
            override_payload = override if override is not None else deepcopy(self.base_override)

            semantic_path.write_text(json.dumps(semantic_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            override_path.write_text(json.dumps(override_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            if metadata_payload is None:
                metadata_path.write_text((ROOT / "data/report_metadata.json").read_text(encoding="utf-8"), encoding="utf-8")
            else:
                metadata_path.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    "tools/render_management_report_tex.py",
                    "--semantic-input",
                    str(semantic_path),
                    "--raw-input",
                    str(raw_path),
                    "--metadata",
                    str(metadata_path),
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

    def _run_render_twice_hashes(self) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "management-report.tex"
            provenance_path = tmp_path / "management-report.provenance.json"

            command = [
                "python3",
                "tools/render_management_report_tex.py",
                "--semantic-input",
                str(self.semantic_path),
                "--raw-input",
                str(self.raw_path),
                "--metadata",
                "data/report_metadata.json",
                "--override",
                "data/mock/management_report_page4_preview_override.json",
                "--output",
                str(output_path),
                "--provenance-output",
                str(provenance_path),
            ]

            first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            first_tex_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            first_prov_hash = hashlib.sha256(provenance_path.read_bytes()).hexdigest()

            second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            second_tex_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            second_prov_hash = hashlib.sha256(provenance_path.read_bytes()).hexdigest()

        return (
            f"{first_tex_hash}:{second_tex_hash}",
            f"{first_prov_hash}:{second_prov_hash}",
        )

    def test_valid_inputs_render_and_record_full_provenance(self) -> None:
        result = self._run_render()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(result.output_exists)
        self.assertTrue(result.provenance_exists)

        tex = result.output_text
        self.assertIn("2 (19)", tex)
        self.assertIn("3 (19)", tex)
        self.assertIn("4 (19)", tex)
        self.assertIn("Förvaltningsberättelse", tex)
        self.assertIn("Flerårsöversikt (Tkr)", tex)
        self.assertIn("Förslag till vinstdisposition", tex)
        self.assertIn("Hållbarhetsupplysningar", tex)
        self.assertNotIn("Hållbarhetsupplysningar - ESG (Environmental, Social and Governance)", tex)
        self.assertNotIn("Uppsala, Oslo", tex)
        self.assertNotIn("Vad beträffar resultat och ställning i övrigt", tex)

        provenance = result.provenance_payload
        assert provenance is not None
        required = {
            "schemaVersion",
            "rendererVersion",
            "semanticContractPath",
            "semanticContractSha256",
            "rawContractPath",
            "rawContractSha256",
            "sourceDocxSha256",
            "metadataPath",
            "metadataSha256",
            "previewOverridePath",
            "previewOverrideSha256",
            "previewOverrideSourceType",
            "previewOverrideApprovalScope",
            "coveredDiagnosticCodes",
            "coveredSourceBlockIds",
            "overriddenFields",
            "signedReferenceCorrections",
            "sourceBlockIdsUsed",
            "outputTexPath",
            "outputTexSha256",
        }
        self.assertTrue(required.issubset(set(provenance.keys())))
        correction_ids = [entry["correctionId"] for entry in provenance["signedReferenceCorrections"]]
        self.assertEqual(len(correction_ids), len(set(correction_ids)))

    def test_tex_and_provenance_are_deterministic(self) -> None:
        tex_pair, prov_pair = self._run_render_twice_hashes()
        tex_a, tex_b = tex_pair.split(":", 1)
        prov_a, prov_b = prov_pair.split(":", 1)
        self.assertEqual(tex_a, tex_b)
        self.assertEqual(prov_a, prov_b)

    def test_missing_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "management-report.tex"
            provenance_path = Path(tmp) / "management-report.provenance.json"
            result = subprocess.run(
                [
                    "python3",
                    "tools/render_management_report_tex.py",
                    "--semantic-input",
                    str(self.semantic_path),
                    "--raw-input",
                    str(self.raw_path),
                    "--metadata",
                    "data/report_metadata.json",
                    "--override",
                    str(Path(tmp) / "missing.json"),
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
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing management-report page-4 preview override", result.stderr)
            self.assertFalse(output_path.exists())
            self.assertFalse(provenance_path.exists())

    def test_wrong_override_source_type_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["sourceType"] = "manual_override"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sourceType", result.stderr)

    def test_wrong_override_approval_scope_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["approvalScope"] = "wrong"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approvalScope", result.stderr)

    def test_wrong_signed_reference_hash_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["signedReference"]["sha256"] = "0" * 64
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_missing_override_schema_version_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override.pop("schemaVersion", None)
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required override fields", result.stderr)

    def test_wrong_company_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["companyName"] = "Wrong AB"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("companyName", result.stderr)

    def test_wrong_organization_number_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["organizationNumber"] = "000000-0000"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("organizationNumber", result.stderr)

    def test_wrong_reporting_period_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["currentReportingPeriod"] = "2024-01-01\n-2024-12-31"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("currentReportingPeriod", result.stderr)

    def test_duplicate_override_row_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["changesInEquity"]["rows"][1]["label"] = "Belopp vid årets ingång"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected changesInEquity row label", result.stderr)

    def test_missing_override_row_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["changesInEquity"]["rows"] = override["changesInEquity"]["rows"][:-1]
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly 4 rows", result.stderr)

    def test_unexpected_override_row_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["changesInEquity"]["rows"].append(
            {"label": "Injected row", "values": ["1", "1", "1", "1", "1"]}
        )
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly 4 rows", result.stderr)

    def test_non_string_financial_value_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["changesInEquity"]["rows"][0]["values"][0] = None
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changesInEquity row value", result.stderr)

    def test_incomplete_overridden_fields_manifest_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["overriddenFields"] = override["overriddenFields"][:-1]
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid overriddenFields manifest", result.stderr)

    def test_unapproved_closing_statement_override_is_rejected(self) -> None:
        override = deepcopy(self.base_override)
        override["profitDisposition"]["closingStatement"] = "Modified closing text"
        result = self._run_render(override=override)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approved signed-reference final paragraph", result.stderr)

    def test_unrelated_review_required_diagnostic_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["diagnostics"].append(
            {
                "code": "UNRELATED_REVIEW_REQUIRED_DIAGNOSTIC",
                "severity": "review_required",
                "message": "synthetic unrelated diagnostic",
                "sourceBlockId": "b9999",
            }
        )
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncovered source blocks", result.stderr)

    def test_unknown_blocking_diagnostic_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["diagnostics"].append(
            {
                "code": "UNKNOWN_BLOCKING_DIAGNOSTIC",
                "severity": "blocking",
                "message": "hard stop",
                "sourceBlockId": "b0020",
            }
        )
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Blocking diagnostic", result.stderr)

    def test_validated_status_with_review_diagnostics_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["status"] = "validated"
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validated", result.stderr)

    def test_review_required_with_uncovered_diagnostic_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["diagnostics"].append(
            {
                "code": "REVIEW_CODE_UNCOVERED",
                "severity": "review_required",
                "message": "must fail",
                "sourceBlockId": "b0020",
            }
        )
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not explicitly covered", result.stderr)

    def test_duplicate_section_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["sections"].append(deepcopy(semantic["sections"][0]))
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate sectionKey", result.stderr)

    def test_unknown_section_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["sections"][0]["sectionKey"] = "unknownSection"
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown sectionKey", result.stderr)

    def test_missing_section_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["sections"] = semantic["sections"][:-1]
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required sections", result.stderr)

    def test_out_of_order_sections_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["sections"][1], semantic["sections"][2] = semantic["sections"][2], semantic["sections"][1]
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact required order", result.stderr)

    def test_duplicate_source_block_usage_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        source_id = semantic["sections"][3]["paragraphs"][0]["sourceBlockId"]
        semantic["sections"][4]["paragraphs"][0]["sourceBlockId"] = source_id
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("used in more than one destination", result.stderr)

    def test_multi_year_label_change_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["tables"][0]["table"]["rows"][6]["cells"][0]["text"] = "Rörelsemarginal procent"
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected multi-year source label", result.stderr)

    def test_raw_contract_hash_mismatch_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["rawContractSha256"] = "0" * 64
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rawContractSha256", result.stderr)

    def test_docx_source_sha_mismatch_rejected(self) -> None:
        semantic = deepcopy(self.base_semantic)
        semantic["sourceEvidence"]["sha256"] = "0" * 64
        result = self._run_render(semantic=semantic)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source DOCX SHA-256", result.stderr)

    def test_body_text_is_preserved_except_latex_escaping(self) -> None:
        semantic = deepcopy(self.base_semantic)
        body_text = "Body  text, punctuation: () [] !? & 100% #1 _x_ {value} $"
        semantic["sections"][3]["paragraphs"][0]["text"] = body_text
        result = self._run_render(semantic=semantic)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        expected_escaped = "Body  text, punctuation: () [] !? \\& 100\\% \\#1 \\_x\\_ \\{value\\} \\$"
        self.assertIn(expected_escaped, result.output_text)
        self.assertNotIn(body_text, result.output_text)

    def test_failed_rerun_removes_stale_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            semantic_path = tmp_path / "semantic.json"
            raw_path = tmp_path / "raw.json"
            override_path = tmp_path / "override.json"
            output_path = tmp_path / "management-report.tex"
            provenance_path = tmp_path / "management-report.provenance.json"

            semantic_path.write_text(json.dumps(self.base_semantic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raw_path.write_text(json.dumps(self.base_raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            override_path.write_text(json.dumps(self.base_override, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            ok = subprocess.run(
                [
                    "python3",
                    "tools/render_management_report_tex.py",
                    "--semantic-input",
                    str(semantic_path),
                    "--raw-input",
                    str(raw_path),
                    "--metadata",
                    "data/report_metadata.json",
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
            self.assertEqual(ok.returncode, 0, msg=ok.stderr)
            self.assertTrue(output_path.exists())
            self.assertTrue(provenance_path.exists())

            bad_override = deepcopy(self.base_override)
            bad_override["approvalScope"] = "bad_scope"
            override_path.write_text(json.dumps(bad_override, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            bad = subprocess.run(
                [
                    "python3",
                    "tools/render_management_report_tex.py",
                    "--semantic-input",
                    str(semantic_path),
                    "--raw-input",
                    str(raw_path),
                    "--metadata",
                    "data/report_metadata.json",
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
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(output_path.exists())
            self.assertFalse(provenance_path.exists())


if __name__ == "__main__":
    unittest.main()
