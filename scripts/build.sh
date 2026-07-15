#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
GENERATED_TEX="$ROOT/generated/income-statement.tex"

mkdir -p "$BUILD"
cd "$ROOT"

if [[ ! -f "$GENERATED_TEX" ]]; then
  mkdir -p "$ROOT/generated"
  python3 tools/render_income_statement_tex.py \
    --input data/mock/income_statement_current_period_fixture.json \
    --output generated/income-statement.tex \
    --previous-period-fixture data/mock/income_statement_previous_period_fixture.json
fi

latexmk \
  -pdf \
  -interaction=nonstopmode \
  -halt-on-error \
  -outdir="$BUILD" \
  template/main.tex

mv -f "$BUILD/main.pdf" "$BUILD/annual-report.pdf"
echo "Built: $BUILD/annual-report.pdf"
