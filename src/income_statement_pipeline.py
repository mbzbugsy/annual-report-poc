from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from income_statement_adapter import (
    IncomeStatementAdapterError,
    adapt_income_statement_for_renderer,
    load_previous_period_source,
)
from income_statement_extractor import ExtractionError, extract_income_statement
from income_statement_provenance import (
    EXPECTED_PDF_PATH,
    EXPECTED_REAL_BUILD_STATUS_PATH,
    EXPECTED_REAL_PARTIAL_PATH,
    EXPECTED_REAL_PROVENANCE_PATH,
    PROVENANCE_SCHEMA_VERSION,
    ProvenanceValidationError,
    compute_file_sha256,
    load_build_status,
    validate_real_build_status,
)
from income_statement_renderer import render_income_statement_tex
from report_metadata import load_report_metadata


class PipelineError(Exception):
    pass


def _run_step(command: List[str], root: Path, step_name: str, *, env: Optional[Dict[str, str]] = None) -> None:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    completed = subprocess.run(command, cwd=root, check=False, env=command_env)
    if completed.returncode != 0:
        raise PipelineError(f"Pipeline step failed: {step_name}")


def _promote_file(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, target)


def run_income_statement_pipeline(
    root: Path,
    *,
    previous_period_source_path: Path,
    previous_period_source_type: str,
    metadata_path: Optional[Path] = None,
    workbook_path: Optional[Path] = None,
) -> None:
    run_id = str(uuid.uuid4())

    previous_source_text = previous_period_source_path.as_posix().strip()
    if previous_source_text in {"", ".", "./"}:
        raise PipelineError("Pipeline configuration error: previous-period source path is required.")

    extraction_input = workbook_path or Path("source-data/Resultaträkning, balansräkning,eget kapital etc.xlsx")
    generated_dir = root / "generated"
    final_extraction_output = generated_dir / "income-statement.json"
    final_adapter_current_output = generated_dir / "income-statement-renderer-input.json"
    final_adapter_previous_output = generated_dir / "income-statement-renderer-previous.json"
    final_adapter_audit_output = generated_dir / "income-statement-adapter-audit.json"
    final_real_tex_output = root / EXPECTED_REAL_PARTIAL_PATH
    final_real_provenance_output = root / EXPECTED_REAL_PROVENANCE_PATH
    final_build_status_output = root / EXPECTED_REAL_BUILD_STATUS_PATH

    generated_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="income-statement-stage-", dir=generated_dir) as staging_tmp:
        staging_dir = Path(staging_tmp)
        staged_extraction_output = staging_dir / "income-statement.json"
        staged_adapter_current_output = staging_dir / "income-statement-renderer-input.json"
        staged_adapter_previous_output = staging_dir / "income-statement-renderer-previous.json"
        staged_adapter_audit_output = staging_dir / "income-statement-adapter-audit.json"
        staged_real_tex_output = staging_dir / "income-statement.real.tex"
        staged_real_provenance_output = staging_dir / "income-statement.real.provenance.json"

        try:
            extraction_payload = extract_income_statement(root / extraction_input, staged_extraction_output)
        except ExtractionError as exc:
            raise PipelineError(f"Pipeline step failed: excel-extraction ({exc})") from exc

        if not staged_extraction_output.exists():
            staged_extraction_output.write_text(
                json.dumps(extraction_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        try:
            metadata = load_report_metadata(root / metadata_path if metadata_path else None)
        except Exception as exc:
            raise PipelineError(f"Pipeline step failed: metadata-validation ({exc})") from exc

        try:
            previous_source_payload = load_previous_period_source(root / previous_period_source_path)
        except IncomeStatementAdapterError as exc:
            raise PipelineError(f"Pipeline step failed: previous-period-source ({exc})") from exc

        try:
            adapted = adapt_income_statement_for_renderer(
                extraction_payload,
                metadata,
                previous_source_payload,
                previous_period_source_type=previous_period_source_type,
                previous_period_source_identifier=previous_period_source_path.as_posix(),
            )
        except IncomeStatementAdapterError as exc:
            raise PipelineError(f"Pipeline step failed: extraction-adapter-validation ({exc})") from exc

        adapted["audit"]["runId"] = run_id
        adapted["rendererCurrentPayload"]["runId"] = run_id
        adapted["rendererPreviousPayload"]["runId"] = run_id

        staged_adapter_current_output.write_text(
            json.dumps(adapted["rendererCurrentPayload"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        staged_adapter_previous_output.write_text(
            json.dumps(adapted["rendererPreviousPayload"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        staged_adapter_audit_output.write_text(
            json.dumps(adapted["audit"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        try:
            render_income_statement_tex(
                staged_adapter_current_output,
                staged_real_tex_output,
                previous_period_fixture_path=staged_adapter_previous_output,
            )
        except Exception as exc:
            raise PipelineError(f"Pipeline step failed: json-to-latex ({exc})") from exc

        if not staged_real_tex_output.exists():
            raise PipelineError("Pipeline step failed: json-to-latex (missing rendered real income partial)")

        real_partial_sha256 = compute_file_sha256(staged_real_tex_output)

        provenance = {
            "schemaVersion": PROVENANCE_SCHEMA_VERSION,
            "mode": "real",
            "adapterStatus": adapted["audit"].get("adapterStatus"),
            "runId": run_id,
            "previousPeriodSourceClassification": adapted["audit"]["sources"]["previousPeriodSource"].get("classification"),
            "previousPeriodSourceIdentifier": adapted["audit"]["sources"]["previousPeriodSource"].get("identifier"),
            "currentExtractionSource": adapted["audit"]["sources"].get("extractor"),
            "realPartialPath": EXPECTED_REAL_PARTIAL_PATH,
            "realPartialSha256": real_partial_sha256,
            "adapterAuditPath": "generated/income-statement-adapter-audit.json",
        }
        staged_real_provenance_output.write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Each os.replace call is atomic on the local filesystem, but this sequence is not transactional as a set.
        # The TeX/provenance hash binding ensures mismatched pairs fail closed in real-mode validation.
        _promote_file(staged_extraction_output, final_extraction_output)
        _promote_file(staged_adapter_current_output, final_adapter_current_output)
        _promote_file(staged_adapter_previous_output, final_adapter_previous_output)
        _promote_file(staged_adapter_audit_output, final_adapter_audit_output)
        _promote_file(staged_real_tex_output, final_real_tex_output)
        _promote_file(staged_real_provenance_output, final_real_provenance_output)

    _run_step(["./scripts/build.sh"], root, "latex-build", env={"INCOME_STATEMENT_MODE": "real"})

    pdf_output = root / EXPECTED_PDF_PATH
    if not pdf_output.exists():
        raise PipelineError("Pipeline step failed: latex-build (missing build/annual-report.pdf)")

    try:
        build_status = load_build_status(final_build_status_output)
        validate_real_build_status(
            build_status,
            expected_run_id=run_id,
            expected_real_partial_sha256=real_partial_sha256,
        )
    except ProvenanceValidationError as exc:
        raise PipelineError(f"Pipeline step failed: latex-build ({exc})") from exc
