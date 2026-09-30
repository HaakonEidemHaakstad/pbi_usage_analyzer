# Development setup

## Recommended environment

Use VS Code with:
- Python extension
- Pylance
- Ruff
- OpenAI Codex extension

Open the repository root, not an individual Python file, so repository
instructions and project context are available to the coding agent.

## Windows bootstrap

From PowerShell in the repository root:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

If `py` is unavailable but `python` works:

    python -m venv .venv

Select `.venv` as the Python interpreter in VS Code.

## Baseline checks

    python -m compileall -q pbi_usage_analyzer tests
    python -m unittest discover -s tests -v

## Synthetic validation

Generate fixtures:

    python tools\validation\generate_validation_suite.py tools\validation\validation_suite --clean

Run the analyzer against expected ground truth:

    python tools\validation\validate_analyzer.py . tools\validation\validation_suite

Some scenarios may intentionally encode desired behavior that the current
implementation has not reached yet. Treat such failures as known development
targets, not as a reason to weaken the expected result.

## Integration test with a PBIP project

    python .\run_analyzer.py "C:\path\to\PowerBIProject"

Do not commit real organizational PBIP data or generated reports unless the
repository policy explicitly permits it.

## Agent workflow

Before substantial work, ask the coding agent to read:
- AGENTS.md
- docs/architecture.md
- docs/ROADMAP.md
- relevant tests

For changes affecting classification, require:
- a regression fixture
- targeted tests
- full test run
- explanation of changed classification counts

Use subagents for independent investigation/review when available, but keep
integration and final verification with the main agent.


## Optional MariaDB integration environment

See `docs/MARIADB_INTEGRATION.md`.

Start:

    .\scripts\integration-up.ps1

Stop:

    .\scripts\integration-down.ps1

Reset:

    .\scripts\integration-reset.ps1

This environment is optional and must never be required by the normal unit
test suite.

## Privileged access

See `docs/PRIVILEGED_ACCESS.md`.

Do not store an operating-system/sudo password for the coding agent. Structure
the development environment so routine work is unprivileged.

## Primary workflow: Ubuntu

The canonical local workflow is now:

    make check
    make setup
    make compile
    make test
    make validate

See `docs/UBUNTU_SETUP.md`.

PowerShell helper scripts remain only for portability/legacy use. New
development automation should prefer POSIX shell and Makefile targets unless a
cross-platform need is explicit.

