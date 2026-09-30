#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Power BI Analyzer - local project setup"
echo "======================================="

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required but was not found."
    exit 1
fi

if [[ ! -d ".venv" ]]; then
    echo "Creating .venv ..."
    python3 -m venv .venv
fi

PY="$ROOT/.venv/bin/python"

echo "Upgrading pip ..."
"$PY" -m pip install --upgrade pip

echo "Installing Python dependencies ..."
"$PY" -m pip install -r requirements.txt

echo "Making repository shell scripts executable ..."
chmod +x scripts/*.sh || true

echo
echo "Running baseline compile check ..."
"$PY" -m compileall -q pbi_usage_analyzer tests tools

echo "Running unit/regression tests ..."
"$PY" -m unittest discover -s tests -v

echo
echo "Setup complete."
echo "VS Code interpreter:"
echo "  $ROOT/.venv/bin/python"
echo
echo "Useful commands:"
echo "  make test"
echo "  make validate"
echo "  make db-up"
