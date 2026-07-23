#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
GENERATED_INCOME_TEX="$ROOT/generated/income-statement.tex"
GENERATED_REAL_INCOME_TEX="$ROOT/generated/income-statement.real.tex"
GENERATED_REAL_INCOME_PROVENANCE="$ROOT/generated/income-statement.real.provenance.json"
GENERATED_REAL_BUILD_STATUS="$ROOT/generated/income-statement.real.build-status.json"
GENERATED_BALANCE_TEX="$ROOT/generated/balance-sheet.tex"
GENERATED_CASH_FLOW_TEX="$ROOT/generated/cash-flow.tex"
GENERATED_METADATA_TEX="$ROOT/generated/report-metadata.tex"
GENERATED_MANAGEMENT_RAW_JSON="$ROOT/generated/management-report-raw.json"
GENERATED_MANAGEMENT_JSON="$ROOT/generated/management-report.json"
GENERATED_MANAGEMENT_TEX="$ROOT/generated/management-report.tex"
GENERATED_MANAGEMENT_PROVENANCE="$ROOT/generated/management-report.provenance.json"
MANAGEMENT_REAL_DOCX="$ROOT/source-data/12_Förvaltningsberättelse_2025.docx"
MANAGEMENT_SYNTHETIC_DOCX="$ROOT/data/mock/management_report_fixture.docx"
MANAGEMENT_PREVIEW_OVERRIDE="$ROOT/data/mock/management_report_page4_preview_override.json"
MANAGEMENT_MODE="${MANAGEMENT_REPORT_MODE:-real}"
INCOME_MODE="${INCOME_STATEMENT_MODE:-synthetic}"

mkdir -p "$BUILD"
cd "$ROOT"

python3 tools/render_report_metadata_tex.py \
  --input data/report_metadata.json \
  --output "$GENERATED_METADATA_TEX"

mkdir -p "$ROOT/generated"

case "$MANAGEMENT_MODE" in
  real)
    if [[ ! -f "$MANAGEMENT_REAL_DOCX" ]]; then
      echo "ERROR: missing management-report DOCX for real mode: $MANAGEMENT_REAL_DOCX" >&2
      exit 1
    fi
    MANAGEMENT_INPUT_DOCX="$MANAGEMENT_REAL_DOCX"
    ;;
  synthetic)
    if [[ ! -f "$MANAGEMENT_SYNTHETIC_DOCX" ]]; then
      echo "ERROR: missing management-report DOCX fixture for synthetic mode: $MANAGEMENT_SYNTHETIC_DOCX" >&2
      exit 1
    fi
    MANAGEMENT_INPUT_DOCX="$MANAGEMENT_SYNTHETIC_DOCX"
    ;;
  *)
    echo "ERROR: unsupported MANAGEMENT_REPORT_MODE value '$MANAGEMENT_MODE'" >&2
    exit 1
    ;;
esac

python3 tools/extract_management_report.py \
  --input "$MANAGEMENT_INPUT_DOCX" \
  --metadata "$ROOT/data/report_metadata.json" \
  --raw-output "$GENERATED_MANAGEMENT_RAW_JSON" \
  --semantic-output "$GENERATED_MANAGEMENT_JSON"

python3 tools/render_management_report_tex.py \
  --semantic-input "$GENERATED_MANAGEMENT_JSON" \
  --raw-input "$GENERATED_MANAGEMENT_RAW_JSON" \
  --metadata "$ROOT/data/report_metadata.json" \
  --override "$MANAGEMENT_PREVIEW_OVERRIDE" \
  --output "$GENERATED_MANAGEMENT_TEX" \
  --provenance-output "$GENERATED_MANAGEMENT_PROVENANCE"

if [[ ! -f "$GENERATED_MANAGEMENT_RAW_JSON" ]]; then
  echo "ERROR: missing generated management-report raw contract: $GENERATED_MANAGEMENT_RAW_JSON" >&2
  exit 1
fi
if [[ ! -f "$GENERATED_MANAGEMENT_JSON" ]]; then
  echo "ERROR: missing generated management-report semantic contract: $GENERATED_MANAGEMENT_JSON" >&2
  exit 1
fi
if [[ ! -f "$GENERATED_MANAGEMENT_TEX" ]]; then
  echo "ERROR: missing generated management-report TeX partial: $GENERATED_MANAGEMENT_TEX" >&2
  exit 1
fi
if [[ ! -f "$GENERATED_MANAGEMENT_PROVENANCE" ]]; then
  echo "ERROR: missing generated management-report provenance: $GENERATED_MANAGEMENT_PROVENANCE" >&2
  exit 1
fi

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

# Intentionally regenerate the synthetic cash-flow partial on every build.
python3 tools/render_cash_flow_tex.py \
  --input data/mock/cash_flow_fixture.json \
  --output "$GENERATED_CASH_FLOW_TEX" \
  --metadata data/report_metadata.json

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
