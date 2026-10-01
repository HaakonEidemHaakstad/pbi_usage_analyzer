# Start the desktop GUI from the project .venv (Windows).
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\gui.ps1 [project folder or .pbip]
param([string]$Project = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $python)) {
    Write-Host "No .venv found. Run: powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Gui"
    exit 1
}
& $python -c "import PySide6" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PySide6 is not installed in .venv. Run: powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Gui"
    exit 1
}

$arguments = @("-m", "pbi_usage_analyzer_gui")
if ($Project) { $arguments += $Project }
# pythonw starts the window without a console.
Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $root
