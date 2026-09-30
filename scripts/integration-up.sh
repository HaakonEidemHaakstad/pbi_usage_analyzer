#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DBDIR="$ROOT/integration/mariadb"
cd "$DBDIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed."
    echo "See docs/UBUNTU_SETUP.md."
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose plugin is not available."
    echo "See docs/UBUNTU_SETUP.md."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed, but this user cannot access the Docker daemon."
    echo "Do not give the coding agent a stored sudo password."
    echo "Configure rootless Docker or Docker access interactively."
    exit 1
fi

if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo
    echo "Created integration/mariadb/.env"
    echo "Edit the two example MariaDB passwords, then run this command again."
    echo
    exit 1
fi

docker compose up -d
docker compose ps
