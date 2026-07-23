# OP Annual Report PoC

A small proof of concept for generating a PDF annual report from LaTeX, structured content files, CSV data, and a focused Excel extraction slice.

## Purpose

This repository is intentionally simple. It is meant to test whether a non-developer can:

1. Open the project in VS Code.
2. Ask an AI agent to update text or financial values.
3. Build a new PDF.
4. Review the changes in Git.

All values and names in this repository are fictional.

## Project structure

```text
.
├── AGENTS.md
├── README.md
├── content/
├── data/
├── generated/
├── scripts/
├── source-data/
├── src/
└── template/
```

- `template/` contains layout and document structure.
- `content/` contains editable report text.
- `data/` contains fictional financial figures.
- `source-data/` contains local real source files used for extraction experiments (git-ignored).
- `src/` contains extraction logic and mapping profiles.
- `generated/` contains generated extraction outputs.
- `scripts/` contains build helpers.

## Prerequisites

Install:

- VS Code
- A LaTeX distribution
  - Windows: MiKTeX
  - macOS: MacTeX
  - Linux: TeX Live
- Optional VS Code extension: LaTeX Workshop

The command `latexmk` must be available in the terminal.

## Build the PDF (clean/mock)

Use this for reproducible builds from a clean checkout (including CI-like local runs).
If `generated/income-statement.tex` is missing, the build script renders it from committed synthetic fixtures.

### PowerShell

```powershell
./scripts/build.ps1
```

### Bash

```bash
./scripts/build.sh
```

The resulting PDF will be written to:

```text
build/annual-report.pdf
```

Synthetic fixtures used for clean/mock build:

- `data/mock/income_statement_current_period_fixture.json`
- `data/mock/income_statement_previous_period_fixture.json`
- `data/mock/management_report_fixture.docx` (synthetic extractor input, used only with `MANAGEMENT_REPORT_MODE=synthetic`)
- `data/mock/management_report_page4_preview_override.json` (required explicit preview override for equity/disposition block)

## Run the income-statement extractor (RR slice)

The current extraction slice reads selected income-statement labels from the real workbook and writes normalized JSON.

Run:

```bash
python3 tools/extract_income_statement.py
```

Output:

```text
generated/income-statement.json
```

Notes:

- This is a read-only extraction over local files in `source-data/`.
- The extractor uses workbook profile settings from `src/income_statement_profile.py`.

## Run the real local Excel pipeline

Use this when you want to extract from the real local workbook in `source-data/` and rebuild the report with those extracted values.

Run:

```bash
python3 tools/build_income_statement_slice.py \
  --previous-period-source /tmp/previous-period-source.json \
  --previous-period-source-type real_extract
```

For synthetic comparison data (explicitly non-production):

```bash
python3 tools/build_income_statement_slice.py \
  --previous-period-source data/mock/income_statement_previous_period_fixture.json \
  --previous-period-source-type synthetic_fixture
```

Output:

```text
build/annual-report.pdf
```

Notes:

- JSON and LaTeX intermediates are written to `generated/`.
- Previous-period source is explicit and required in this command; there is no silent fallback.
- `synthetic_fixture` classification is allowed for testing but does not produce a fully real two-period report.
- Replace synthetic comparison data with a real previous-period source for production workflows.

Real-mode build status contract:

- `INCOME_STATEMENT_MODE=real ./scripts/build.sh` validates real provenance/hash, builds the PDF, and then writes/refreshed `generated/income-statement.real.build-status.json`.
- The same build-status contract applies whether real mode is run directly via `scripts/build.sh` or indirectly via `tools/build_income_statement_slice.py`.
- Failed real-mode builds leave no `status: succeeded` real build-status file behind.

## Extract management report from DOCX (deterministic JSON contracts)

The management-report extractor reads the local Word source and writes two JSON artifacts:

- ordered raw DOCX block contract
- validated semantic management-report contract

Run:

```bash
python3 tools/extract_management_report.py \
  --input source-data/12_Förvaltningsberättelse_2025.docx \
  --metadata data/report_metadata.json \
  --raw-output generated/management-report-raw.json \
  --semantic-output generated/management-report.json
```

Output:

- `generated/management-report-raw.json`
- `generated/management-report.json`

## Render management report LaTeX (pages 2-4)

Render deterministic management-report pages from the extracted semantic+raw contracts:

```bash
python3 tools/render_management_report_tex.py \
  --semantic-input generated/management-report.json \
  --raw-input generated/management-report-raw.json \
  --metadata data/report_metadata.json \
  --override data/mock/management_report_page4_preview_override.json \
  --output generated/management-report.tex \
  --provenance-output generated/management-report.provenance.json
```

Output:

- `generated/management-report.tex`
- `generated/management-report.provenance.json`

Contract notes:

- Narrative and multi-year overview are rendered from the semantic management-report contract.
- Equity/profit-disposition rendering is fail-closed and requires committed explicit preview override.
- Override contract must declare:
  - `sourceType = signed_reference_preview_override`
  - `approvalScope = poc_preview_only`
  - signed reference SHA-256 for `source-data/Omegapoint-Malmo-AB-Arsredovisning-2025-signed-14411061.pdf`

Contract notes:

- Output is deterministic for identical input bytes and metadata.
- No wall-clock extraction timestamp is emitted.
- Source evidence includes filename, SHA-256, and DOCX core-property timestamps.
- Raw contract preserves physical paragraph/table order, runs, styles, break markers, table shapes, and source trace.
- Semantic contract maps required headings/sections deterministically and records explicit exclusions for:
  - internal template/helper instructions
  - post-report note-update material after explicit boundary detection
- Semantic policy is fail-closed for meaningful unsupported content (for example hidden text, tracked changes, field codes, and text boxes with content).
- Decorative non-text drawing/pict constructs are preserved as reviewable semantic diagnostics:
  - `UNSUPPORTED_DECORATIVE_DRAWING_PRESENT`
  - `UNSUPPORTED_DECORATIVE_PICT_PRESENT`
- The current source policy marks semantic status as `review_required` with `EQUITY_DISPOSITION_SOURCE_AUTHORITY_UNRESOLVED` until equity/disposition authority is formally approved.
- The extractor does not render LaTeX and does not require the signed PDF.

Build mode policy:

- `MANAGEMENT_REPORT_MODE=real` (default) requires `source-data/12_Förvaltningsberättelse_2025.docx`, runs `tools/extract_management_report.py`, and fails closed on missing/invalid inputs.
- `MANAGEMENT_REPORT_MODE=synthetic` runs the same extractor against `data/mock/management_report_fixture.docx`.
- No committed semantic JSON fixture is copied into `generated/` by default build or CI.

Output promotion behavior:

- The CLI stages raw and semantic JSON in temporary files under each destination directory.
- Final files are promoted only after both contracts are successfully built and serialized.
- Promotion order is raw then semantic using `os.replace` per file (same-filesystem atomic for each file).
- If the process is interrupted between promotions, consumers must compare `semantic.rawContractSha256` with the actual raw file hash to detect a mismatch.
- On failure before promotion, existing final raw/semantic files are left unchanged and staging files are cleaned up.

## Suggested first agent test

Ask the agent:

> Update the CEO statement to mention that the fictional company expanded into two new markets. Do not change the layout. Build the PDF after the change.

Then review:

- Which files changed?
- Did the agent respect `AGENTS.md`?
- Did the document compile?
- Did the layout remain intact?

## Next steps after the PoC

- Replace fictional content with approved test material.
- Decide how Excel data should be imported.
- Add validation for required fields.
- Extend CI checks beyond PDF build as extraction scope grows.
- Add branch protection in the target DevOps environment.
