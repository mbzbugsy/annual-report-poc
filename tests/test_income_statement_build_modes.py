from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IncomeStatementBuildModeTests(unittest.TestCase):
    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _setup_fake_workspace(self, tmp: Path) -> Path:
        (tmp / "scripts").mkdir(parents=True, exist_ok=True)
        (tmp / "tools").mkdir(parents=True, exist_ok=True)
        (tmp / "src").mkdir(parents=True, exist_ok=True)
        (tmp / "data" / "mock").mkdir(parents=True, exist_ok=True)
        (tmp / "template").mkdir(parents=True, exist_ok=True)
        (tmp / "generated").mkdir(parents=True, exist_ok=True)
        (tmp / "bin").mkdir(parents=True, exist_ok=True)

        build_script = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")
        self._write_executable(tmp / "scripts" / "build.sh", build_script)

        validator_tool = (ROOT / "tools" / "validate_income_statement_provenance.py").read_text(encoding="utf-8")
        self._write_executable(tmp / "tools" / "validate_income_statement_provenance.py", validator_tool)
        writer_tool = (ROOT / "tools" / "write_income_statement_build_status.py").read_text(encoding="utf-8")
        self._write_executable(tmp / "tools" / "write_income_statement_build_status.py", writer_tool)
        provenance_module = (ROOT / "src" / "income_statement_provenance.py").read_text(encoding="utf-8")
        self._write_executable(tmp / "src" / "income_statement_provenance.py", provenance_module)

        self._write_executable(
            tmp / "tools" / "render_report_metadata_tex.py",
            """#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text('METADATA\\n', encoding='utf-8')
""",
        )

        self._write_executable(
            tmp / "tools" / "render_income_statement_tex.py",
            """#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');p.add_argument('--previous-period-fixture');a=p.parse_args()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text('SYNTHETIC_INCOME_PARTIAL\\n', encoding='utf-8')
""",
        )

        self._write_executable(
            tmp / "tools" / "render_balance_sheet_tex.py",
            """#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');p.add_argument('--previous-period-fixture');a=p.parse_args()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text('BALANCE_PARTIAL\\n', encoding='utf-8')
""",
        )

        self._write_executable(
            tmp / "tools" / "render_cash_flow_tex.py",
            """#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');p.add_argument('--metadata');a=p.parse_args()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text('CASH_FLOW_PARTIAL\\n', encoding='utf-8')
""",
        )

        self._write_executable(
            tmp / "tools" / "extract_management_report.py",
            """#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--metadata');p.add_argument('--raw-output');p.add_argument('--semantic-output');a=p.parse_args()
Path(a.raw_output).parent.mkdir(parents=True, exist_ok=True)
Path(a.raw_output).write_text('{"source":{"file":"data/mock/management_report_fixture.docx","sha256":"abc"}}\\n', encoding='utf-8')
Path(a.semantic_output).write_text('{"status":"review_required","rawContractSha256":"abc"}\\n', encoding='utf-8')
""",
        )

        self._write_executable(
            tmp / "tools" / "render_management_report_tex.py",
            """#!/usr/bin/env python3
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--semantic-input');p.add_argument('--raw-input');p.add_argument('--metadata');p.add_argument('--override');p.add_argument('--output');p.add_argument('--provenance-output');a=p.parse_args()
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text('MANAGEMENT_PARTIAL\\n', encoding='utf-8')
Path(a.provenance_output).write_text('{"schemaVersion":"2.0"}\\n', encoding='utf-8')
""",
        )

        self._write_executable(
            tmp / "bin" / "latexmk",
            """#!/usr/bin/env bash
set -euo pipefail
outdir=''
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-outdir="* ]]; then
    outdir="${1#-outdir=}"
  fi
  shift
done
mkdir -p "$outdir"
printf 'PDF' > "$outdir/main.pdf"
""",
        )

        (tmp / "data" / "report_metadata.json").write_text("{}\n", encoding="utf-8")
        (tmp / "data" / "mock" / "income_statement_current_period_fixture.json").write_text("{}\n", encoding="utf-8")
        (tmp / "data" / "mock" / "income_statement_previous_period_fixture.json").write_text("{}\n", encoding="utf-8")
        (tmp / "data" / "mock" / "balance_sheet_current_period_fixture.json").write_text("{}\n", encoding="utf-8")
        (tmp / "data" / "mock" / "balance_sheet_previous_period_fixture.json").write_text("{}\n", encoding="utf-8")
        (tmp / "data" / "mock" / "cash_flow_fixture.json").write_text("{}\n", encoding="utf-8")
        (tmp / "data" / "mock" / "management_report_fixture.docx").write_text("fixture\n", encoding="utf-8")
        (tmp / "data" / "mock" / "management_report_page4_preview_override.json").write_text("{}\n", encoding="utf-8")
        (tmp / "template" / "main.tex").write_text("% test\n", encoding="utf-8")

        return tmp

    def _sha256(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _sha256_bytes(self, value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def _load_build_status(self, root: Path) -> dict[str, object]:
        return json.loads((root / "generated" / "income-statement.real.build-status.json").read_text(encoding="utf-8"))

    def _load_provenance(self, root: Path) -> dict[str, object]:
        return json.loads((root / "generated" / "income-statement.real.provenance.json").read_text(encoding="utf-8"))

    def _run_build(self, root: Path, mode: str | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{root / 'bin'}:{env['PATH']}"
        env["MANAGEMENT_REPORT_MODE"] = "synthetic"
        if mode is None:
            env.pop("INCOME_STATEMENT_MODE", None)
        else:
            env["INCOME_STATEMENT_MODE"] = mode
        return subprocess.run(
            ["./scripts/build.sh"],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _write_real_provenance(
        self,
        root: Path,
        *,
        classification: str = "real_extract",
        run_id: str = "11111111-1111-1111-1111-111111111111",
        real_partial_path: str = "generated/income-statement.real.tex",
        real_partial_sha256: str | None = None,
        adapter_status: str = "validated",
        mode: str = "real",
        identifier: str = "/tmp/previous.json",
    ) -> None:
        if real_partial_sha256 is None:
            real_path = root / "generated" / "income-statement.real.tex"
            if real_path.exists():
                real_text = real_path.read_text(encoding="utf-8")
                real_partial_sha256 = self._sha256(real_text)
            else:
                real_partial_sha256 = "0" * 64

        provenance = {
            "schemaVersion": "1.1",
            "mode": mode,
            "adapterStatus": adapter_status,
            "runId": run_id,
            "previousPeriodSourceClassification": classification,
            "previousPeriodSourceIdentifier": identifier,
            "currentExtractionSource": {"file": "input.xlsx", "sheet": "RR"},
            "realPartialPath": real_partial_path,
            "realPartialSha256": real_partial_sha256,
            "adapterAuditPath": "generated/income-statement-adapter-audit.json",
        }
        (root / "generated" / "income-statement.real.provenance.json").write_text(
            json.dumps(provenance) + "\n", encoding="utf-8"
        )

    def test_default_build_does_not_reuse_stale_real_income_statement_tex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.tex").write_text("REAL_STALE\n", encoding="utf-8")
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")

            result = self._run_build(root)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            content = (root / "generated" / "income-statement.tex").read_text(encoding="utf-8")
            self.assertIn("SYNTHETIC_INCOME_PARTIAL", content)
            self.assertNotIn("REAL_STALE", content)
            self.assertNotIn("REAL_VALIDATED", content)

    def test_default_build_never_consumes_real_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")

            result = self._run_build(root)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            content = (root / "generated" / "income-statement.tex").read_text(encoding="utf-8")
            self.assertEqual(content, "SYNTHETIC_INCOME_PARTIAL\n")

    def test_default_build_does_not_touch_real_build_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            status_path = root / "generated" / "income-statement.real.build-status.json"
            status_path.write_text('{"status":"succeeded","runId":"old"}\n', encoding="utf-8")

            before = status_path.read_text(encoding="utf-8")
            result = self._run_build(root)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(status_path.read_text(encoding="utf-8"), before)

    def test_real_mode_fails_when_real_partial_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            self._write_real_provenance(root)
            stale_status = root / "generated" / "income-statement.real.build-status.json"
            stale_status.write_text('{"status":"succeeded","runId":"old"}\n', encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("income-statement.real.tex", result.stderr)
            self.assertFalse(stale_status.exists())

    def test_real_mode_fails_when_provenance_missing_or_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            stale_status = root / "generated" / "income-statement.real.build-status.json"
            stale_status.write_text('{"status":"succeeded","runId":"old"}\n', encoding="utf-8")

            missing = self._run_build(root, mode="real")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("provenance", missing.stderr)
            self.assertFalse(stale_status.exists())

            self._write_real_provenance(root, adapter_status="review_required")
            invalid = self._run_build(root, mode="real")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("adapterStatus", invalid.stderr)

    def test_real_mode_rejects_non_object_provenance_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            (root / "generated" / "income-statement.real.provenance.json").write_text("[1,2,3]\n", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("provenance shape", result.stderr)

    def test_real_mode_rejects_provenance_missing_real_partial_path_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)
            provenance_path = root / "generated" / "income-statement.real.provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("realPartialPath", None)
            provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("realPartialPath", result.stderr)

    def test_real_mode_fails_when_provenance_is_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            (root / "generated" / "income-statement.real.provenance.json").write_text("{bad", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid real income provenance JSON", result.stderr)

    def test_real_mode_rejects_provenance_with_wrong_mode_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, mode="synthetic")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mode must be 'real'", result.stderr)

    def test_real_mode_rejects_provenance_with_invalid_adapter_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, adapter_status="review_required")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("adapterStatus", result.stderr)

    def test_real_mode_rejects_unsupported_provenance_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, classification="unsupported")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid previousPeriodSourceClassification", result.stderr)

    def test_real_mode_rejects_provenance_with_mismatched_partial_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, real_partial_path="generated/other.tex")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("realPartialPath mismatch", result.stderr)

    def test_real_mode_rejects_provenance_with_missing_source_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, identifier="")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("previousPeriodSourceIdentifier", result.stderr)

    def test_real_mode_rejects_provenance_with_missing_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)
            provenance_path = root / "generated" / "income-statement.real.provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("runId", None)
            provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("runId", result.stderr)

    def test_real_mode_rejects_non_canonical_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, run_id="11111111111111111111111111111111")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("runId", result.stderr)

    def test_real_mode_rejects_missing_real_partial_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)
            provenance_path = root / "generated" / "income-statement.real.provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.pop("realPartialSha256", None)
            provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("realPartialSha256", result.stderr)

    def test_real_mode_rejects_malformed_real_partial_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, real_partial_sha256="ABC123")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("realPartialSha256 format", result.stderr)

    def test_real_mode_rejects_wrong_real_partial_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, real_partial_sha256="0" * 64)

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash mismatch", result.stderr)

    def test_real_mode_rejects_partial_modified_after_provenance_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            real_partial = root / "generated" / "income-statement.real.tex"
            real_partial.write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)

            # Tamper with the real partial after provenance was created.
            real_partial.write_text("TAMPERED\n", encoding="utf-8")
            (root / "generated" / "income-statement.tex").write_text("SHARED_OLD\n", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash mismatch", result.stderr)
            self.assertEqual(
                (root / "generated" / "income-statement.tex").read_text(encoding="utf-8"),
                "SHARED_OLD\n",
            )
            self.assertFalse((root / "build" / "annual-report.pdf").exists())

    def test_interrupted_promotion_leaves_hash_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            real_partial = root / "generated" / "income-statement.real.tex"

            # Prior valid pair.
            real_partial.write_text("OLD_REAL\n", encoding="utf-8")
            self._write_real_provenance(root)

            # Simulate interrupted promotion: new real partial promoted, old provenance still present.
            real_partial.write_text("NEW_REAL\n", encoding="utf-8")
            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash mismatch", result.stderr)

    def test_unknown_income_build_mode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            result = self._run_build(root, mode="unknown")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported INCOME_STATEMENT_MODE", result.stderr)

    def test_real_mode_uses_validated_real_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, classification="manual_override")

            result = self._run_build(root, mode="real")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            shared = (root / "generated" / "income-statement.tex").read_text(encoding="utf-8")
            self.assertEqual(shared, "REAL_VALIDATED\n")

            build_status = self._load_build_status(root)
            provenance = self._load_provenance(root)
            actual_real_hash = self._sha256_bytes((root / "generated" / "income-statement.real.tex").read_bytes())

            self.assertEqual(build_status["status"], "succeeded")
            self.assertEqual(build_status["mode"], "real")
            self.assertEqual(build_status["runId"], provenance["runId"])
            self.assertEqual(build_status["realPartialSha256"], provenance["realPartialSha256"])
            self.assertEqual(build_status["realPartialSha256"], actual_real_hash)
            self.assertEqual(build_status["pdfPath"], "build/annual-report.pdf")
            self.assertEqual(
                build_status["provenancePath"],
                "generated/income-statement.real.provenance.json",
            )

    def test_real_mode_refreshes_old_mismatched_build_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, run_id="22222222-2222-2222-2222-222222222222")
            (root / "generated" / "income-statement.real.build-status.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "runId": "11111111-1111-1111-1111-111111111111",
                        "status": "succeeded",
                        "mode": "real",
                        "pdfPath": "build/annual-report.pdf",
                        "provenancePath": "generated/income-statement.real.provenance.json",
                        "realPartialSha256": "0" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = self._run_build(root, mode="real")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            build_status = self._load_build_status(root)
            provenance = self._load_provenance(root)
            self.assertEqual(build_status["runId"], provenance["runId"])
            self.assertEqual(build_status["realPartialSha256"], provenance["realPartialSha256"])

    def test_real_mode_latex_failure_leaves_no_succeeded_build_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)
            (root / "generated" / "income-statement.real.build-status.json").write_text(
                '{"status":"succeeded","runId":"old"}\n',
                encoding="utf-8",
            )
            self._write_executable(
                root / "bin" / "latexmk",
                """#!/usr/bin/env bash
set -euo pipefail
echo 'latexmk failed' >&2
exit 2
""",
            )

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "generated" / "income-statement.real.build-status.json").exists())

    def test_real_mode_missing_pdf_leaves_no_succeeded_build_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)
            (root / "generated" / "income-statement.real.build-status.json").write_text(
                '{"status":"succeeded","runId":"old"}\n',
                encoding="utf-8",
            )
            self._write_executable(
                root / "bin" / "latexmk",
                """#!/usr/bin/env bash
set -euo pipefail
outdir=''
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-outdir="* ]]; then
    outdir="${1#-outdir=}"
  fi
  shift
done
mkdir -p "$outdir"
exit 0
""",
            )

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "generated" / "income-statement.real.build-status.json").exists())

    def test_real_mode_rejects_uppercase_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)
            provenance_path = root / "generated" / "income-statement.real.provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["realPartialSha256"] = provenance["realPartialSha256"].upper()
            provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")

            result = self._run_build(root, mode="real")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("realPartialSha256 format", result.stderr)

    def test_real_run_followed_by_default_build_ends_with_synthetic_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root)

            real_result = self._run_build(root, mode="real")
            self.assertEqual(real_result.returncode, 0, msg=real_result.stderr)
            self.assertEqual(
                (root / "generated" / "income-statement.tex").read_text(encoding="utf-8"),
                "REAL_VALIDATED\n",
            )

            synthetic_result = self._run_build(root)
            self.assertEqual(synthetic_result.returncode, 0, msg=synthetic_result.stderr)
            self.assertEqual(
                (root / "generated" / "income-statement.tex").read_text(encoding="utf-8"),
                "SYNTHETIC_INCOME_PARTIAL\n",
            )

    def test_cash_flow_render_failure_cannot_compile_stale_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            stale_marker = "STALE_CASH_FLOW\n"
            (root / "generated" / "cash-flow.tex").write_text(stale_marker, encoding="utf-8")

            self._write_executable(
                root / "tools" / "render_cash_flow_tex.py",
                """#!/usr/bin/env python3
import sys
print('ERROR: cash-flow render failed', file=sys.stderr)
raise SystemExit(1)
""",
            )

            self._write_executable(
                root / "bin" / "latexmk",
                """#!/usr/bin/env bash
set -euo pipefail
touch build/latexmk.invoked
outdir=''
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-outdir="* ]]; then
    outdir="${1#-outdir=}"
  fi
  shift
done
mkdir -p "$outdir"
printf 'PDF' > "$outdir/main.pdf"
""",
            )

            result = self._run_build(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cash-flow render failed", result.stderr)
            self.assertEqual((root / "generated" / "cash-flow.tex").read_text(encoding="utf-8"), stale_marker)
            self.assertFalse((root / "build" / "latexmk.invoked").exists())
            self.assertFalse((root / "build" / "annual-report.pdf").exists())

    def test_real_income_mode_still_renders_synthetic_cash_flow_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.real.tex").write_text("REAL_VALIDATED\n", encoding="utf-8")
            self._write_real_provenance(root, classification="real_extract")

            # If this marker appears, a real cash-flow extractor was called unexpectedly.
            real_extractor_marker = root / "generated" / "real-cash-flow-extractor.invoked"
            self._write_executable(
                root / "tools" / "extract_cash_flow.py",
                f"""#!/usr/bin/env python3
from pathlib import Path
Path({str(real_extractor_marker)!r}).write_text('invoked\n', encoding='utf-8')
raise SystemExit(99)
""",
            )

            result = self._run_build(root, mode="real")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            cash_flow = root / "generated" / "cash-flow.tex"
            self.assertTrue(cash_flow.exists())
            self.assertEqual(cash_flow.read_text(encoding="utf-8"), "CASH_FLOW_PARTIAL\n")
            self.assertFalse(real_extractor_marker.exists())

            build_status = self._load_build_status(root)
            provenance = self._load_provenance(root)
            self.assertEqual(build_status["status"], "succeeded")
            self.assertEqual(build_status["mode"], "real")
            self.assertEqual(build_status["runId"], provenance["runId"])
            self.assertEqual(build_status["realPartialSha256"], provenance["realPartialSha256"])

    def test_synthetic_render_failure_cannot_compile_stale_shared_real_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = self._setup_fake_workspace(Path(tmp_dir))
            (root / "generated" / "income-statement.tex").write_text("STALE_REAL\n", encoding="utf-8")

            self._write_executable(
                root / "tools" / "render_income_statement_tex.py",
                """#!/usr/bin/env python3
import sys
print('ERROR: synthetic render failed', file=sys.stderr)
raise SystemExit(1)
""",
            )

            result = self._run_build(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                (root / "generated" / "income-statement.tex").read_text(encoding="utf-8"),
                "STALE_REAL\n",
            )
            self.assertFalse((root / "build" / "annual-report.pdf").exists())


if __name__ == "__main__":
    unittest.main()
