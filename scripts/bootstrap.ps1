# -Gui also installs the optional desktop GUI dependencies (PySide6).
param([switch]$Gui)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -m venv .venv
    } else {
        python -m venv .venv
    }
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($Gui) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
}

Write-Host ""
Write-Host "Environment ready."
Write-Host "Select .venv as the Python interpreter in VS Code."
Write-Host "Run tests with:"
Write-Host "  .\.venv\Scripts\python.exe -m unittest discover -s tests -v"
if ($Gui) {
    Write-Host "Start the GUI with:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\gui.ps1"
}
