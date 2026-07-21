from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_pipeline import PipelineError, run_income_statement_pipeline
from income_statement_provenance import EXPECTED_REAL_PARTIAL_PATH


class IncomeStatementPipelineTests(unittest.TestCase):
    def _metadata_stub(self):
        return type(
            "M",
            (),
            {
                "current_reporting_period": "2025-01-01\n-2025-12-31",
                "previous_reporting_period": "2024-01-01\n-2024-12-31",
            },
        )()

    def _extraction_payload(self) -> dict[str, object]:
        return {
            "source": {"file": "x.xlsx", "sheet": "RR sammanställning"},
            "lines": {
                "revenue": {"value": "1"},
                "otherOperatingIncome": {"value": "1"},
                "totalIncome": {"value": "1"},
                "operatingResult": {"value": "1"},
                "resultAfterFinancialItems": {"value": "1"},
                "profitBeforeTax": {"value": "1"},
                "taxForYear": {"value": "1"},
                "netResult": {"value": "1"},
            },
            "period": {"reportingPeriod": None},
        }

    def _previous_source(self) -> dict[str, object]:
        return {
            "periodLabel": "2024-01-01\n-2024-12-31",
            "values": {
                "revenue": "1",
                "otherOperatingIncome": "1",
                "totalIncome": "1",
                "operatingResult": "1",
                "resultAfterFinancialItems": "1",
                "profitBeforeTax": "1",
                "taxForYear": "1",
                "netResult": "1",
            },
        }

    def _sha256_bytes(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_build_status_from_provenance(
        self,
        root: Path,
        *,
        run_id_override: str | None = None,
        hash_override: str | None = None,
    ) -> None:
        generated = root / "generated"
        provenance = json.loads((generated / "income-statement.real.provenance.json").read_text(encoding="utf-8"))
        build_status = {
            "schemaVersion": "1.0",
            "runId": run_id_override or provenance["runId"],
            "status": "succeeded",
            "mode": "real",
            "pdfPath": "build/annual-report.pdf",
            "provenancePath": "generated/income-statement.real.provenance.json",
            "realPartialSha256": hash_override or provenance["realPartialSha256"],
        }
        (generated / "income-statement.real.build-status.json").write_text(
            json.dumps(build_status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_stops_if_json_to_latex_generation_fails(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()
        render_mock.side_effect = Exception("renderer failed")

        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            (generated / "income-statement.real.tex").write_text("BASELINE_REAL_TEX\n", encoding="utf-8")

            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    Path(tmp),
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertEqual(
                (generated / "income-statement.real.tex").read_text(encoding="utf-8"),
                "BASELINE_REAL_TEX\n",
            )
            self.assertFalse((generated / "income-statement.real.provenance.json").exists())

        self.assertIn("json-to-latex", str(ctx.exception))
        self.assertEqual(run_mock.call_count, 0)

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_staging_directory_removed_after_renderer_failure(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()
        render_mock.side_effect = Exception("renderer failed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PipelineError):
                run_income_statement_pipeline(
                    root,
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            stage_dirs = list((root / "generated").glob("income-statement-stage-*"))
            self.assertEqual(stage_dirs, [])

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_renderer_is_not_called_when_adapter_validation_fails(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        payload = self._extraction_payload()
        payload["status"] = "review_required"
        extract_mock.return_value = payload
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            baseline = generated / "income-statement.json"
            baseline.write_text('{"baseline": true}\n', encoding="utf-8")
            before = baseline.read_text(encoding="utf-8")

            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    Path(tmp),
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertEqual((generated / "income-statement.json").read_text(encoding="utf-8"), before)
            self.assertFalse((generated / "income-statement-renderer-input.json").exists())
            self.assertFalse((generated / "income-statement-renderer-previous.json").exists())
            self.assertFalse((generated / "income-statement-adapter-audit.json").exists())
            self.assertFalse((generated / "income-statement.real.tex").exists())

        self.assertIn("extraction-adapter-validation", str(ctx.exception))
        render_mock.assert_not_called()
        self.assertEqual(run_mock.call_count, 0)

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_staging_directory_removed_after_adapter_failure(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        payload = self._extraction_payload()
        payload["status"] = "review_required"
        extract_mock.return_value = payload
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PipelineError):
                run_income_statement_pipeline(
                    root,
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            stage_dirs = list((root / "generated").glob("income-statement-stage-*"))
            self.assertEqual(stage_dirs, [])

        render_mock.assert_not_called()
        self.assertEqual(run_mock.call_count, 0)

    def test_missing_explicit_previous_period_source_rejected(self) -> None:
        with self.assertRaises(PipelineError) as ctx:
            run_income_statement_pipeline(
                ROOT,
                previous_period_source_path=Path(""),
                previous_period_source_type="real_extract",
            )
        self.assertIn("previous-period source path is required", str(ctx.exception))

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_successful_validation_promotes_outputs_and_invokes_real_mode_build(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(args=["./scripts/build.sh"], returncode=0)
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "build").mkdir(parents=True, exist_ok=True)

            def _run_side_effect(*args, **kwargs):
                (root / "build" / "annual-report.pdf").write_text("PDF", encoding="utf-8")
                self._write_build_status_from_provenance(root)
                return subprocess.CompletedProcess(args=args[0], returncode=0)

            run_mock.side_effect = _run_side_effect

            run_income_statement_pipeline(
                root,
                previous_period_source_path=Path("previous.json"),
                previous_period_source_type="real_extract",
                metadata_path=Path("metadata.json"),
                workbook_path=Path("input.xlsx"),
            )

            generated = root / "generated"
            self.assertTrue((generated / "income-statement.json").exists())
            self.assertTrue((generated / "income-statement-renderer-input.json").exists())
            self.assertTrue((generated / "income-statement-renderer-previous.json").exists())
            self.assertTrue((generated / "income-statement-adapter-audit.json").exists())
            self.assertTrue((generated / "income-statement.real.tex").exists())
            provenance_path = generated / "income-statement.real.provenance.json"
            self.assertTrue(provenance_path.exists())
            build_status_path = generated / "income-statement.real.build-status.json"
            self.assertTrue(build_status_path.exists())

            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(provenance["mode"], "real")
            self.assertEqual(provenance["adapterStatus"], "validated")
            self.assertEqual(provenance["previousPeriodSourceClassification"], "real_extract")
            self.assertEqual(provenance["realPartialPath"], EXPECTED_REAL_PARTIAL_PATH)
            self.assertRegex(provenance["runId"], r"^[0-9a-f-]{36}$")
            self.assertRegex(provenance["realPartialSha256"], r"^[0-9a-f]{64}$")

            audit = json.loads((generated / "income-statement-adapter-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["runId"], provenance["runId"])

            renderer_current = json.loads((generated / "income-statement-renderer-input.json").read_text(encoding="utf-8"))
            renderer_previous = json.loads((generated / "income-statement-renderer-previous.json").read_text(encoding="utf-8"))
            self.assertEqual(renderer_current["runId"], provenance["runId"])
            self.assertEqual(renderer_previous["runId"], provenance["runId"])

            expected_hash = self._sha256_bytes(generated / "income-statement.real.tex")
            self.assertEqual(provenance["realPartialSha256"], expected_hash)

            build_status = json.loads(build_status_path.read_text(encoding="utf-8"))
            self.assertEqual(build_status["status"], "succeeded")
            self.assertEqual(build_status["mode"], "real")
            self.assertEqual(build_status["runId"], provenance["runId"])
            self.assertEqual(build_status["realPartialSha256"], provenance["realPartialSha256"])
            self.assertEqual(build_status["pdfPath"], "build/annual-report.pdf")
            self.assertEqual(build_status["provenancePath"], "generated/income-statement.real.provenance.json")

            stage_dirs = list(generated.glob("income-statement-stage-*"))
            self.assertEqual(stage_dirs, [])

        self.assertEqual(run_mock.call_count, 1)
        env_used = run_mock.call_args.kwargs["env"]
        self.assertEqual(env_used.get("INCOME_STATEMENT_MODE"), "real")

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_build_failure_after_promotion_does_not_write_new_succeeded_status(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect
        run_mock.return_value = subprocess.CompletedProcess(args=["./scripts/build.sh"], returncode=1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            stale_status_path = generated / "income-statement.real.build-status.json"
            stale_status_path.write_text('{"status":"succeeded","runId":"old"}\n', encoding="utf-8")

            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    root,
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertIn("latex-build", str(ctx.exception))
            self.assertTrue(stale_status_path.exists())
            self.assertTrue((generated / "income-statement.real.provenance.json").exists())

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_rejects_missing_build_status_after_successful_build(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _run_side_effect(*args, **kwargs):
                (root / "build").mkdir(parents=True, exist_ok=True)
                (root / "build" / "annual-report.pdf").write_text("PDF", encoding="utf-8")
                return subprocess.CompletedProcess(args=args[0], returncode=0)

            run_mock.side_effect = _run_side_effect

            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    root,
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertIn("build-status", str(ctx.exception))

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_rejects_mismatched_build_status_run_id(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _run_side_effect(*args, **kwargs):
                (root / "build").mkdir(parents=True, exist_ok=True)
                (root / "build" / "annual-report.pdf").write_text("PDF", encoding="utf-8")
                self._write_build_status_from_provenance(
                    root,
                    run_id_override="22222222-2222-2222-2222-222222222222",
                )
                return subprocess.CompletedProcess(args=args[0], returncode=0)

            run_mock.side_effect = _run_side_effect

            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    root,
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertIn("runId mismatch", str(ctx.exception))

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_rejects_mismatched_build_status_hash(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _run_side_effect(*args, **kwargs):
                (root / "build").mkdir(parents=True, exist_ok=True)
                (root / "build" / "annual-report.pdf").write_text("PDF", encoding="utf-8")
                self._write_build_status_from_provenance(root, hash_override="0" * 64)
                return subprocess.CompletedProcess(args=args[0], returncode=0)

            run_mock.side_effect = _run_side_effect

            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    root,
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertIn("realPartialSha256 mismatch", str(ctx.exception))

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_missing_pdf_after_successful_build_step_raises_error(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect
        run_mock.return_value = subprocess.CompletedProcess(args=["./scripts/build.sh"], returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    Path(tmp),
                    previous_period_source_path=Path("previous.json"),
                    previous_period_source_type="real_extract",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

            self.assertIn("missing build/annual-report.pdf", str(ctx.exception))

    @patch("income_statement_pipeline.render_income_statement_tex")
    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_interrupted_promotion_between_real_tex_and_provenance_is_fail_closed(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
        render_mock,
    ) -> None:
        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.return_value = self._previous_source()

        def _render_side_effect(current_json, output_tex, previous_period_fixture_path=None):
            output_tex.write_text("NEW_REAL_TEX\n", encoding="utf-8")

        render_mock.side_effect = _render_side_effect
        run_mock.return_value = subprocess.CompletedProcess(args=["./scripts/build.sh"], returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir(parents=True, exist_ok=True)

            # Prior valid pair.
            prior_real_path = generated / "income-statement.real.tex"
            prior_real_path.write_text("OLD_REAL_TEX\n", encoding="utf-8")
            prior_hash = self._sha256_bytes(prior_real_path)
            (generated / "income-statement.real.provenance.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.1",
                        "mode": "real",
                        "adapterStatus": "validated",
                        "runId": "11111111-1111-1111-1111-111111111111",
                        "previousPeriodSourceClassification": "real_extract",
                        "previousPeriodSourceIdentifier": "/tmp/prior.json",
                        "currentExtractionSource": {"file": "old.xlsx", "sheet": "RR"},
                        "realPartialPath": "generated/income-statement.real.tex",
                        "realPartialSha256": prior_hash,
                        "adapterAuditPath": "generated/income-statement-adapter-audit.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            import income_statement_pipeline as pipeline_module

            original_promote = pipeline_module._promote_file

            def crashing_promote(staged: Path, target: Path) -> None:
                original_promote(staged, target)
                if target.name == "income-statement.real.tex":
                    raise RuntimeError("simulated interruption after real.tex promotion")

            with mock.patch("income_statement_pipeline._promote_file", side_effect=crashing_promote):
                with self.assertRaises(RuntimeError):
                    run_income_statement_pipeline(
                        root,
                        previous_period_source_path=Path("previous.json"),
                        previous_period_source_type="real_extract",
                        metadata_path=Path("metadata.json"),
                        workbook_path=Path("input.xlsx"),
                    )

            new_real_hash = self._sha256_bytes(prior_real_path)
            stale_provenance_hash = json.loads(
                (generated / "income-statement.real.provenance.json").read_text(encoding="utf-8")
            )["realPartialSha256"]
            self.assertNotEqual(new_real_hash, stale_provenance_hash)

    @patch("income_statement_pipeline.load_previous_period_source")
    @patch("income_statement_pipeline.load_report_metadata")
    @patch("income_statement_pipeline.extract_income_statement")
    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_never_falls_back_to_committed_synthetic_fixture_after_source_failure(
        self,
        run_mock,
        extract_mock,
        metadata_mock,
        previous_source_mock,
    ) -> None:
        from income_statement_adapter import IncomeStatementAdapterError

        extract_mock.return_value = self._extraction_payload()
        metadata_mock.return_value = self._metadata_stub()
        previous_source_mock.side_effect = IncomeStatementAdapterError("bad previous source")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PipelineError) as ctx:
                run_income_statement_pipeline(
                    Path(tmp),
                    previous_period_source_path=Path("explicit.json"),
                    previous_period_source_type="manual_override",
                    metadata_path=Path("metadata.json"),
                    workbook_path=Path("input.xlsx"),
                )

        self.assertIn("previous-period-source", str(ctx.exception))
        self.assertEqual(run_mock.call_count, 0)


if __name__ == "__main__":
    unittest.main()
