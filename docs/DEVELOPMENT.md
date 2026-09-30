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
    python -m pip install -r requirements-dev.txt

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


## Continuous integration

`.github/workflows/ci.yml` runs compilation, unit/regression tests, and synthetic
validation on Ubuntu 24.04 / Python 3.12. It uses the same Make targets as local
development and installs `requirements-dev.txt` into `.venv`. No Docker service
or organizational credentials are needed. Pip packages are downloaded from the
configured package index; requirements remain version ranges rather than a lockfile.

The workflow triggers on pushes, pull requests, and manual dispatch. New runs
cancel obsolete runs for the same ref. Actions are pinned by commit, and the job
has read-only repository permissions and a 15-minute timeout. Update action pins
when adopting reviewed upstream releases. Local validation does not establish
that a hosted Actions run succeeded; inspect GitHub's checks after publishing.

## Fixture drift checks

`make check-fixtures` invokes the generator in a temporary directory and compares
relative file names and contents against the corpus. It never cleans or rewrites
the reference directory. Missing/extra/changed files fail the check, including
unexpected generated analysis reports. Symlinks are rejected. Empty directories
and file metadata are outside the comparison contract. CI includes this target.

When changing fixtures, edit the generator and expected results intentionally,
regenerate with `make fixtures`, inspect the diff, then run `make check-fixtures`
and `make validate`. The clean regeneration target replaces the corpus; move any
unrelated work out of that directory first.

## Optional real-project check

`tests/test_integration_adventureworks.py` compares every status with
`tests/integration/adventureworks_expected.json` when `PBI_AW_PROJECT` names the
folder containing `AdventureWorks Report.pbip`; otherwise it is skipped. The
project is not committed. Update the expectations only after explaining each
change against the project files.

## Performance check

`make benchmark` generates a large synthetic model in a temporary folder
(`tools/validation/large_model.py`: 40 tables, about 3,300 objects) and prints
object/evidence counts and the best of three analysis times. CI runs it for
information only. `tests/test_large_model.py` checks a smaller generated model's
classifications by default; set `PBI_PERF=1` to also assert the full model
analyzes in under 3 seconds. The generated model has no ground truth beyond those
samples and is not part of the committed fixture corpus.

`tests/test_determinism.py` compares full JSON exports of every scenario under two
hash seeds. Do not iterate `set`s when producing evidence or findings.

## Runtime-only smoke test

Run `make check-runtime` to create a disposable venv, install only runtime
requirements, and run API/CLI analysis plus report exports against a temporary
fixture. The worker confirms that the development-only `jsonschema` package is
unavailable and that library calls do not write project files. CLI exports are
checked for health-filter scope, nonempty text, and a readable workbook archive.
The worker runs with Python isolation and without inherited Python search paths.
Temporary directories are removed on completion or failure. The target installs
packages, so it needs package-index access or cached wheels. CI runs it after
full validation; it does not replace regression or schema validation tests.
