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


def run_balance_sheet_pipeline(root: Path) -> None:
    _run_step(
        [
            sys.executable,
            "tools/render_balance_sheet_tex.py",
            "--input",
            "data/mock/balance_sheet_current_period_fixture.json",
            "--output",
            "generated/balance-sheet.tex",
            "--previous-period-fixture",
            "data/mock/balance_sheet_previous_period_fixture.json",
        ],
        root,
        "json-to-latex-balance-sheet",
    )
    _run_step(["./scripts/build.sh"], root, "latex-build")
