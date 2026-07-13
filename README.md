# OP Annual Report PoC

A small proof of concept for generating a PDF annual report from LaTeX, structured content files, and CSV data.

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
├── assets/
├── content/
├── data/
├── scripts/
└── template/
```

- `template/` contains layout and document structure.
- `content/` contains editable report text.
- `data/` contains fictional financial figures.
- `assets/` contains images and logos.
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
- Add CI build and PDF artifact generation.
- Add branch protection in the target DevOps environment.
