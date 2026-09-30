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

Write-Host ""
Write-Host "Environment ready."
Write-Host "Select .venv as the Python interpreter in VS Code."
Write-Host "Run tests with:"
Write-Host "  .\.venv\Scripts\python.exe -m unittest discover -s tests -v"
