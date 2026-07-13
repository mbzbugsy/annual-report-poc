$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build"

New-Item -ItemType Directory -Force -Path $Build | Out-Null

Push-Location $Root
try {
    latexmk `
        -pdf `
        -interaction=nonstopmode `
        -halt-on-error `
        -outdir="$Build" `
        template/main.tex

    $Generated = Join-Path $Build "main.pdf"
    $Target = Join-Path $Build "annual-report.pdf"

    if (Test-Path $Generated) {
        Move-Item -Force $Generated $Target
    }

    Write-Host "Built: $Target"
}
finally {
    Pop-Location
}
