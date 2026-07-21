#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
GENERATED_INCOME_TEX="$ROOT/generated/income-statement.tex"
GENERATED_REAL_INCOME_TEX="$ROOT/generated/income-statement.real.tex"
GENERATED_REAL_INCOME_PROVENANCE="$ROOT/generated/income-statement.real.provenance.json"
GENERATED_REAL_BUILD_STATUS="$ROOT/generated/income-statement.real.build-status.json"
GENERATED_BALANCE_TEX="$ROOT/generated/balance-sheet.tex"
GENERATED_METADATA_TEX="$ROOT/generated/report-metadata.tex"
INCOME_MODE="${INCOME_STATEMENT_MODE:-synthetic}"

mkdir -p "$BUILD"
cd "$ROOT"

python3 tools/render_report_metadata_tex.py \
  --input data/report_metadata.json \
  --output "$GENERATED_METADATA_TEX"

mkdir -p "$ROOT/generated"

case "$INCOME_MODE" in
  synthetic)
    python3 tools/render_income_statement_tex.py \
      --input data/mock/income_statement_current_period_fixture.json \
      --output generated/income-statement.tex \
      --previous-period-fixture data/mock/income_statement_previous_period_fixture.json
    ;;
  real)
    rm -f "$GENERATED_REAL_BUILD_STATUS"

    python3 tools/validate_income_statement_provenance.py \
      --real-partial "$GENERATED_REAL_INCOME_TEX" \
      --provenance "$GENERATED_REAL_INCOME_PROVENANCE"

    cp "$GENERATED_REAL_INCOME_TEX" "$GENERATED_INCOME_TEX"
    ;;
  *)
    echo "ERROR: unsupported INCOME_STATEMENT_MODE value '$INCOME_MODE'" >&2
    exit 1
    ;;
esac

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

if [[ "$INCOME_MODE" == "real" ]]; then
  if [[ ! -f "$BUILD/annual-report.pdf" ]]; then
    echo "ERROR: missing build/annual-report.pdf" >&2
    exit 1
  fi

  python3 tools/write_income_statement_build_status.py \
    --real-partial "$GENERATED_REAL_INCOME_TEX" \
    --provenance "$GENERATED_REAL_INCOME_PROVENANCE" \
    --pdf "$BUILD/annual-report.pdf" \
    --output "$GENERATED_REAL_BUILD_STATUS"
fi

echo "Built: $BUILD/annual-report.pdf"
