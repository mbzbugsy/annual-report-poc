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

## Build the PDF

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

## Run the full income-statement vertical slice

Run:

```bash
python3 tools/build_income_statement_slice.py
```

Output:

```text
build/annual-report.pdf
```

Notes:

- JSON and LaTeX intermediates are written to `generated/`.
- Previous-period values for visual comparison are sourced from the synthetic fixture `data/mock/income_statement_previous_period_fixture.json`.
- The fixture is temporary and must be replaced later by a dedicated previous-year workbook import.

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
