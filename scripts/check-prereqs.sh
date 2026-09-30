#!/usr/bin/env bash
set -euo pipefail

fail=0

check_cmd() {
    local cmd="$1"
    local label="$2"

    if command -v "$cmd" >/dev/null 2>&1; then
        printf "[OK]   %-18s %s\n" "$label" "$(command -v "$cmd")"
    else
        printf "[MISS] %-18s not found\n" "$label"
        fail=1
    fi
}

echo "Power BI Analyzer - Ubuntu prerequisite check"
echo "================================================"
check_cmd python3 "python3"
check_cmd git "git"
check_cmd docker "docker"
check_cmd code "VS Code (code)"

echo

if command -v python3 >/dev/null 2>&1; then
    if python3 -m venv --help >/dev/null 2>&1; then
        echo "[OK]   python3-venv       available"
    else
        echo "[MISS] python3-venv       unavailable"
        fail=1
    fi
fi

if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
        echo "[OK]   docker compose     available"
    else
        echo "[MISS] docker compose     plugin unavailable"
        fail=1
    fi

    if docker info >/dev/null 2>&1; then
        echo "[OK]   docker access      current user can talk to Docker"
    else
        echo "[WARN] docker access      Docker exists but current user cannot access the daemon"
        echo "       Do not store a sudo password for the agent."
        echo "       Prefer rootless Docker or explicitly configure Docker access yourself."
    fi
fi

echo
if [[ "$fail" -eq 0 ]]; then
    echo "Core prerequisites look good."
    exit 0
else
    echo "One or more prerequisites are missing."
    echo "See docs/UBUNTU_SETUP.md for the recommended setup workflow."
    exit 1
fi
