#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
GENERATED_INCOME_TEX="$ROOT/generated/income-statement.tex"
GENERATED_BALANCE_TEX="$ROOT/generated/balance-sheet.tex"
GENERATED_METADATA_TEX="$ROOT/generated/report-metadata.tex"

mkdir -p "$BUILD"
cd "$ROOT"

python3 tools/render_report_metadata_tex.py \
  --input data/report_metadata.json \
  --output "$GENERATED_METADATA_TEX"

mkdir -p "$ROOT/generated"

if [[ ! -f "$GENERATED_INCOME_TEX" ]]; then
  python3 tools/render_income_statement_tex.py \
    --input data/mock/income_statement_current_period_fixture.json \
    --output generated/income-statement.tex \
    --previous-period-fixture data/mock/income_statement_previous_period_fixture.json
fi

if [[ ! -f "$GENERATED_BALANCE_TEX" ]]; then
  python3 tools/render_balance_sheet_tex.py \
    --input data/mock/balance_sheet_current_period_fixture.json \
    --output generated/balance-sheet.tex \
    --previous-period-fixture data/mock/balance_sheet_previous_period_fixture.json
fi

latexmk \
  -pdf \
  -interaction=nonstopmode \
  -halt-on-error \
  -outdir="$BUILD" \
  template/main.tex

mv -f "$BUILD/main.pdf" "$BUILD/annual-report.pdf"
echo "Built: $BUILD/annual-report.pdf"
