from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from income_statement_pipeline import PipelineError, run_income_statement_pipeline


class IncomeStatementPipelineTests(unittest.TestCase):
    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_stops_if_json_to_latex_generation_fails(self, run_mock) -> None:
        run_mock.side_effect = [
            subprocess.CompletedProcess(args=["extract"], returncode=0),
            subprocess.CompletedProcess(args=["render"], returncode=2),
            subprocess.CompletedProcess(args=["build"], returncode=0),
        ]

        with self.assertRaises(PipelineError) as ctx:
            run_income_statement_pipeline(ROOT)

        self.assertIn("json-to-latex", str(ctx.exception))
        self.assertEqual(run_mock.call_count, 2)

    @patch("income_statement_pipeline.subprocess.run")
    def test_pipeline_forwards_previous_period_fixture_path(self, run_mock) -> None:
        run_mock.side_effect = [
            subprocess.CompletedProcess(args=["extract"], returncode=0),
            subprocess.CompletedProcess(args=["render"], returncode=0),
            subprocess.CompletedProcess(args=["build"], returncode=0),
        ]

        run_income_statement_pipeline(ROOT)

        self.assertEqual(run_mock.call_count, 3)
        second_call_command = run_mock.call_args_list[1].args[0]
        self.assertIn("--previous-period-fixture", second_call_command)
        self.assertIn(
            "data/mock/income_statement_previous_period_fixture.json",
            second_call_command,
        )


if __name__ == "__main__":
    unittest.main()
