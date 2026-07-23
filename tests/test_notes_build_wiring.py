from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NotesBuildWiringTests(unittest.TestCase):
    def _requires_latex_and_gs(self) -> bool:
        return shutil.which("latexmk") is not None and shutil.which("gs") is not None

    def _run_build(
        self,
        workspace: Path,
        *,
        management_mode: str = "synthetic",
        notes_mode: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["MANAGEMENT_REPORT_MODE"] = management_mode
        if notes_mode is None:
            env.pop("NOTES_MODE", None)
        else:
            env["NOTES_MODE"] = notes_mode
        return subprocess.run(
            ["./scripts/build.sh"],
            cwd=workspace,
            text=True,
            encoding="utf-8",
            errors="replace",
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

    def test_build_script_defines_notes_real_default_and_synthetic_mode(self) -> None:
        build_script = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")
        self.assertIn("NOTES_MODE=\"${NOTES_MODE:-real}\"", build_script)
        self.assertIn("NOTES_REAL_WORKBOOK=", build_script)
        self.assertIn("NOTES_SYNTHETIC_WORKBOOK=", build_script)
        self.assertIn("tools/extract_notes.py", build_script)
        self.assertIn("tools/render_notes_tex.py", build_script)
        self.assertNotIn("notes semantic fixture", build_script)

    def test_ci_uses_synthetic_notes_extraction_and_rendering(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "build-report.yml").read_text(encoding="utf-8")
        self.assertIn("NOTES_MODE: synthetic", workflow)
        self.assertIn("data/mock/notes_workbook_fixture.xlsx", workflow)
        self.assertIn("tools/extract_notes.py", workflow)
        self.assertIn("tools/render_notes_tex.py", workflow)
        self.assertNotIn("cp data/mock/notes.json", workflow)

    def test_main_template_includes_notes_exactly_once_after_financials(self) -> None:
        main_tex = (ROOT / "template" / "main.tex").read_text(encoding="utf-8")
        self.assertEqual(main_tex.count("\\input{generated/notes.tex}"), 1)
        self.assertLess(main_tex.find("\\input{content/financial-summary}"), main_tex.find("\\input{generated/notes.tex}"))

    def test_default_real_mode_fails_when_real_notes_workbook_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )
            (workspace / "source-data" / "Not uppgifterna.xlsx").unlink(missing_ok=True)

            result = self._run_build(workspace, management_mode="synthetic", notes_mode=None)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing notes workbook", result.stderr)
            self.assertFalse((workspace / "build/annual-report.pdf").exists())
            self.assertFalse((workspace / "generated/notes.tex").exists())
            self.assertFalse((workspace / "generated/notes.provenance.json").exists())

    def test_forced_notes_extractor_failure_stops_before_latexmk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            extractor = workspace / "tools" / "extract_notes.py"
            extractor.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('forced notes extractor failure', file=sys.stderr)\nsys.exit(1)\n",
                encoding="utf-8",
            )
            extractor.chmod(0o755)

            result = self._run_build(workspace, management_mode="synthetic", notes_mode="synthetic")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forced notes extractor failure", result.stderr)
            self.assertFalse((workspace / "build/annual-report.pdf").exists())
            self.assertFalse((workspace / "generated/notes.tex").exists())
            self.assertFalse((workspace / "generated/notes.provenance.json").exists())

    def test_forced_notes_renderer_failure_removes_stale_outputs_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            generated = workspace / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            stale_tex = generated / "notes.tex"
            stale_prov = generated / "notes.provenance.json"
            stale_tex.write_text("STALE\n", encoding="utf-8")
            stale_prov.write_text("{}\n", encoding="utf-8")

            renderer = workspace / "tools" / "render_notes_tex.py"
            renderer.write_text(
                "#!/usr/bin/env python3\n"
                "import argparse\n"
                "from pathlib import Path\n"
                "import sys\n"
                "p=argparse.ArgumentParser();"
                "p.add_argument('--semantic-input');p.add_argument('--raw-input');p.add_argument('--metadata');"
                "p.add_argument('--mapping');p.add_argument('--management-contract');p.add_argument('--override');"
                "p.add_argument('--output');p.add_argument('--provenance-output');"
                "a=p.parse_args();"
                "Path(a.output).unlink(missing_ok=True);"
                "Path(a.provenance_output).unlink(missing_ok=True);"
                "print('forced notes renderer failure', file=sys.stderr);"
                "sys.exit(1)\n",
                encoding="utf-8",
            )
            renderer.chmod(0o755)

            result = self._run_build(workspace, management_mode="synthetic", notes_mode="synthetic")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forced notes renderer failure", result.stderr)
            self.assertFalse(stale_tex.exists())
            self.assertFalse(stale_prov.exists())
            self.assertFalse((workspace / "build/annual-report.pdf").exists())

    def test_synthetic_build_produces_19_pages_with_expected_notes_boundaries(self) -> None:
        if not self._requires_latex_and_gs():
            self.skipTest("latexmk or gs not available")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(".git", "build", "generated", "__pycache__", ".pytest_cache"),
            )

            result = self._run_build(workspace, management_mode="synthetic", notes_mode="synthetic")
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotIn("Overfull \\hbox", result.stdout + result.stderr)
            self.assertNotIn("Underfull \\hbox", result.stdout + result.stderr)

            pdf = workspace / "build" / "annual-report.pdf"
            self.assertTrue(pdf.exists())
            self.assertEqual(self._page_count(pdf), 19)

            provenance_path = workspace / "generated" / "notes.provenance.json"
            self.assertTrue(provenance_path.exists())
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertIn("notes", provenance)
            self.assertEqual(len(provenance["notes"].keys()), 28)
            for note_number in range(1, 29):
                self.assertIn(str(note_number), provenance["notes"])
                self.assertIn("renderAuthority", provenance["notes"][str(note_number)])

            page8 = self._extract_page_text(pdf, 8)
            page9 = self._extract_page_text(pdf, 9)
            page19 = self._extract_page_text(pdf, 19)
            self.assertIn("Kassaflödesanalys", page8)
            self.assertIn("Not 1", page9)
            self.assertIn("Not 27", page19)
            self.assertIn("Not 28", page19)


if __name__ == "__main__":
    unittest.main()
