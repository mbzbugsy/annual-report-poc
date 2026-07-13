#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"

mkdir -p "$BUILD"
cd "$ROOT"

latexmk \
  -pdf \
  -interaction=nonstopmode \
  -halt-on-error \
  -outdir="$BUILD" \
  template/main.tex

mv -f "$BUILD/main.pdf" "$BUILD/annual-report.pdf"
echo "Built: $BUILD/annual-report.pdf"
