$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = (Resolve-Path (Join-Path $scriptDir "..")).Path
$venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Error "Expected virtual environment Python at $venvPython. Run 'uv sync --locked' from the project root first."
}

$env:QUARTO_PYTHON = if ($env:QUARTO_PYTHON) { $env:QUARTO_PYTHON } else { $venvPython }
$env:UV_CACHE_DIR = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { (Join-Path $rootDir ".uv_cache") }

Set-Location $rootDir
& uv run quarto @args
exit $LASTEXITCODE
