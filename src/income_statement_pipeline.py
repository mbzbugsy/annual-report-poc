from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List


class PipelineError(Exception):
    pass


def _run_step(command: List[str], root: Path, step_name: str) -> None:
    completed = subprocess.run(command, cwd=root, check=False)
    if completed.returncode != 0:
        raise PipelineError(f"Pipeline step failed: {step_name}")


def run_income_statement_pipeline(root: Path) -> None:
    _run_step(
        [
            sys.executable,
            "tools/extract_income_statement.py",
            "--input",
            "source-data/Resultaträkning, balansräkning,eget kapital etc.xlsx",
            "--output",
            "generated/income-statement.json",
        ],
        root,
        "excel-extraction",
    )
    _run_step(
        [
            sys.executable,
            "tools/render_income_statement_tex.py",
            "--input",
            "generated/income-statement.json",
            "--output",
            "generated/income-statement.tex",
            "--previous-period-fixture",
            "data/mock/income_statement_previous_period_fixture.json",
        ],
        root,
        "json-to-latex",
    )
    _run_step(["./scripts/build.sh"], root, "latex-build")
