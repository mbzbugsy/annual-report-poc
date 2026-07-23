from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ManagementReportBuildWiringTests(unittest.TestCase):
    def _requires_latex_and_gs(self) -> bool:
        return shutil.which("latexmk") is not None and shutil.which("gs") is not None

    def _run_build(self, workspace: Path, mode: str | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["NOTES_MODE"] = "synthetic"
        if mode is None:
            env.pop("MANAGEMENT_REPORT_MODE", None)
        else:
            env["MANAGEMENT_REPORT_MODE"] = mode
        return subprocess.run(
            ["./scripts/build.sh"],
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def _extract_page_text(self, pdf: Path, page: int) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"p{page}.txt"
            gs = subprocess.run(
                [
                    "gs",
                    "-q",
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-sDEVICE=txtwrite",
                    f"-dFirstPage={page}",
                    f"-dLastPage={page}",
                    f"-sOutputFile={out}",
                    str(pdf),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(gs.returncode, 0, msg=gs.stderr)
            return out.read_text(encoding="utf-8", errors="replace")

    def _page_count(self, pdf: Path) -> int:
        result = subprocess.run(
            [
                "gs",
                "-q",
                "-dNOSAFER",
                "-dNODISPLAY",
                "-c",
                f"({pdf}) (r) file runpdfbegin pdfpagecount = quit",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return int(result.stdout.strip())

    def test_template_includes_only_generated_management_narrative_source(self) -> None:
        main_tex = (ROOT / "template" / "main.tex").read_text(encoding="utf-8")
        self.assertIn("\\input{generated/management-report.tex}", main_tex)
        self.assertNotIn("\\input{content/company-overview}", main_tex)
        self.assertNotIn("\\input{content/ceo-statement}", main_tex)
        self.assertNotIn("\\input{content/sustainability}", main_tex)

    def test_build_script_defines_real_default_and_synthetic_mode(self) -> None:
        build_script = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")
        self.assertIn("MANAGEMENT_MODE=\"${MANAGEMENT_REPORT_MODE:-real}\"", build_script)
        self.assertIn("MANAGEMENT_REAL_DOCX=", build_script)
        self.assertIn("MANAGEMENT_SYNTHETIC_DOCX=", build_script)
        self.assertIn("--input \"$MANAGEMENT_INPUT_DOCX\"", build_script)
        self.assertIn("--raw-output \"$GENERATED_MANAGEMENT_RAW_JSON\"", build_script)
        self.assertNotIn("fallback_no_management_contract", build_script)
        self.assertNotIn("management_report_semantic_fixture.json", build_script)

    def test_ci_uses_synthetic_docx_extraction_without_semantic_copy(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "build-report.yml").read_text(encoding="utf-8")
        self.assertIn("MANAGEMENT_REPORT_MODE: synthetic", workflow)
        self.assertIn("tools/extract_management_report.py", workflow)
        self.assertIn("data/mock/management_report_fixture.docx", workflow)
        self.assertIn("--raw-output generated/management-report-raw.json", workflow)
        self.assertNotIn("management_report_semantic_fixture.json", workflow)
        self.assertNotIn("cp data/mock/management_report_semantic_fixture.json", workflow)

    def test_default_real_mode_fails_when_real_docx_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )
            real_docx = workspace / "source-data/12_Förvaltningsberättelse_2025.docx"
            real_docx.unlink(missing_ok=True)

            result = self._run_build(workspace)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing management-report DOCX", result.stderr)
            self.assertFalse((workspace / "build/annual-report.pdf").exists())

    def test_explicit_synthetic_mode_uses_fixture_and_produces_raw_semantic_tex_provenance(self) -> None:
        if not self._requires_latex_and_gs():
            self.skipTest("latexmk or gs not available")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            result = self._run_build(workspace, mode="synthetic")
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            self.assertTrue((workspace / "generated/management-report-raw.json").exists())
            self.assertTrue((workspace / "generated/management-report.json").exists())
            self.assertTrue((workspace / "generated/management-report.tex").exists())
            self.assertTrue((workspace / "generated/management-report.provenance.json").exists())
            self.assertTrue((workspace / "generated/notes-workbook-raw.json").exists())
            self.assertTrue((workspace / "generated/notes.json").exists())
            self.assertTrue((workspace / "generated/notes.tex").exists())
            self.assertTrue((workspace / "generated/notes.provenance.json").exists())
            self.assertTrue((workspace / "build/annual-report.pdf").exists())

            page_count = self._page_count(workspace / "build/annual-report.pdf")
            self.assertEqual(page_count, 19)

            page5 = self._extract_page_text(workspace / "build/annual-report.pdf", 5)
            page8 = self._extract_page_text(workspace / "build/annual-report.pdf", 8)
            page9 = self._extract_page_text(workspace / "build/annual-report.pdf", 9)
            self.assertIn("Resultaträkning", page5)
            self.assertIn("Kassaflödesanalys", page8)
            self.assertIn("Not 1", page9)

    def test_forced_extractor_failure_stops_before_latexmk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )
            extractor = workspace / "tools/extract_management_report.py"
            extractor.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('forced extractor failure', file=sys.stderr)\nsys.exit(1)\n",
                encoding="utf-8",
            )
            extractor.chmod(0o755)

            result = self._run_build(workspace, mode="synthetic")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forced extractor failure", result.stderr)
            self.assertFalse((workspace / "build/annual-report.pdf").exists())

    def test_forced_renderer_failure_removes_stale_outputs_and_stops_before_latexmk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            generated = workspace / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            stale_tex = generated / "management-report.tex"
            stale_prov = generated / "management-report.provenance.json"
            stale_tex.write_text("STALE\n", encoding="utf-8")
            stale_prov.write_text("{}\n", encoding="utf-8")

            renderer = workspace / "tools/render_management_report_tex.py"
            renderer.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import argparse\n"
                "import sys\n"
                "p=argparse.ArgumentParser();"
                "p.add_argument('--output');p.add_argument('--provenance-output');p.add_argument('--semantic-input');"
                "p.add_argument('--raw-input');p.add_argument('--metadata');p.add_argument('--override');"
                "a=p.parse_args();"
                "Path(a.output).unlink(missing_ok=True);"
                "Path(a.provenance_output).unlink(missing_ok=True);"
                "print('forced renderer failure', file=sys.stderr);"
                "sys.exit(1)\n",
                encoding="utf-8",
            )
            renderer.chmod(0o755)

            result = self._run_build(workspace, mode="synthetic")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forced renderer failure", result.stderr)
            self.assertFalse(stale_tex.exists())
            self.assertFalse(stale_prov.exists())
            self.assertFalse((workspace / "build/annual-report.pdf").exists())

    def test_management_report_include_has_no_hbox_warnings(self) -> None:
        if not self._requires_latex_and_gs():
            self.skipTest("latexmk or gs not available")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            result = self._run_build(workspace, mode="real")
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            log_text = (workspace / "build" / "main.log").read_text(encoding="utf-8", errors="replace")
            start = log_text.find("(./generated/management-report.tex")
            self.assertNotEqual(start, -1, msg="management-report include not found in LaTeX log")
            end = log_text.find("(./content/financial-summary.tex", start)
            if end == -1:
                end = len(log_text)
            include_block = log_text[start:end]

            self.assertNotIn("Overfull \\hbox", include_block)
            self.assertNotIn("Underfull \\hbox", include_block)


if __name__ == "__main__":
    unittest.main()
