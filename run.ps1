param([switch]$Setup)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($Setup -or -not (Test-Path -LiteralPath $taskPython)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        if (-not (Test-Path -LiteralPath $taskPython)) {
            uv venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
        }
        uv sync --locked --extra dev
    } else {
        if (-not (Test-Path -LiteralPath $taskPython)) {
            python -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer first.' }
        }
        & $taskPython -m pip install -e '.[dev]'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed. Check your internet connection.' }
}
& $taskPython -m observer
exit $LASTEXITCODE
