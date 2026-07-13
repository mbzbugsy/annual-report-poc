# Agent instructions

## Goal

Maintain a stable annual-report template while allowing safe updates to report text, figures, tables, and images.

## General rules

- Treat all financial values as sensitive business data.
- Never invent, infer, or estimate financial figures.
- Do not copy real internal data into this proof of concept.
- Keep changes small, focused, and easy to review.
- Always explain which files were changed.

## File ownership

### Safe to edit without explicit approval

- `content/*.tex`
- `data/*.csv`
- `assets/` when replacing an explicitly requested image
- Documentation files such as `README.md`

### Do not edit unless explicitly requested

- `template/layout.tex`
- `template/main.tex`
- Build scripts
- Repository configuration

## LaTeX rules

- Preserve margins, typography, page size, and section ordering.
- Do not add LaTeX packages unless explicitly approved.
- Reuse existing commands and environments.
- Escape LaTeX special characters when needed:
  - `&` as `\&`
  - `%` as `\%`
  - `_` as `\_`
  - `#` as `\#`
- Keep Swedish characters encoded as UTF-8.
- Do not manually add page numbers or table-of-contents entries.

## Data rules

- Keep the CSV column names unchanged.
- Do not change numeric values unless the user explicitly provides the replacement values.
- Preserve the unit used in the source file.
- If a requested value is missing, stop and ask for the value instead of guessing.

## Validation

After every content or data change:

1. Build the document.
2. Fix compilation errors caused by the change.
3. Confirm that `build/annual-report.pdf` was produced.
4. Summarize the result and any warnings.

## Example tasks

Good:

> Replace the CEO statement with the supplied text and build the PDF.

Good:

> Update revenue for 2025 to 128.4 MSEK using the exact value provided.

Not allowed:

> Make the financial results look more realistic.

Not allowed:

> Redesign the report to look more modern.
