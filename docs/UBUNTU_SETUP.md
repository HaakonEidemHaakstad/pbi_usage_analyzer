# Ubuntu development setup

Ubuntu/Linux is the primary development environment for this repository.

## 1. Open the repository root

In a terminal:

    cd /path/to/pbi_usage_analyzer_ubuntu_agentic
    code .

Open the whole repository, not an individual Python file.

## 2. Check prerequisites

    ./scripts/check-prereqs.sh

or:

    make check

The project expects:

- Python 3
- Python venv support
- Git
- VS Code
- Docker + Docker Compose plugin for optional MariaDB integration tests

Docker is optional for the normal analyzer/unit-test workflow.

## 3. Python environment

Run:

    ./scripts/setup.sh

or:

    make setup

This creates:

    .venv/

and installs `requirements.txt`.

Select this interpreter in VS Code:

    .venv/bin/python

## 4. Baseline validation

    make compile
    make test
    make validate

The synthetic validation suite intentionally represents desired behavior.
A failing scenario may indicate a known development target rather than a bad
fixture. Do not weaken expected results merely to make the suite green.

## 5. Docker / MariaDB

Check whether Docker is already installed:

    docker --version
    docker compose version

If either command is missing, install Docker using the official Docker
installation instructions for your Ubuntu release.

The repository intentionally does not auto-install system packages or run
privileged package-manager commands. Host-level installation should remain an
explicit user action.

Once Docker works for the current user:

    make db-up

The first run creates:

    integration/mariadb/.env

Edit the two example database passwords. These are disposable local
development credentials only.

Run `make db-up` again.

Useful commands:

    make db-up
    make db-down
    make db-reset

## Docker permissions

Do not store the user's sudo password for the agent.

If `docker info` fails because the current account cannot access Docker, prefer
one of these approaches:

1. configure rootless Docker
2. explicitly configure Docker access yourself after reviewing the security
   implications
3. perform the occasional privileged host action interactively

Do not create blanket passwordless sudo for the coding agent.

## 6. Analyze a PBIP project

Example:

    make analyze PROJECT="/home/user/PowerBI/Forvaltningskunder"

Equivalent direct command:

    .venv/bin/python run_analyzer.py "/home/user/PowerBI/Forvaltningskunder"

## 7. Recommended agent workflow

Before a substantial change, ask Codex to read:

- AGENTS.md
- docs/architecture.md
- docs/ROADMAP.md
- docs/DEVELOPMENT.md
- relevant tests/fixtures

For parser/classification changes, require:

1. reproduce in a synthetic fixture
2. add or confirm expected ground truth
3. run targeted tests
4. run `make test`
5. run `make validate`
6. inspect git diff
7. explain changed classification behavior

Use subagents for independent investigation/review when they materially help.
