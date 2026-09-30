.PHONY: help check setup compile test validate fixtures db-up db-down db-reset analyze clean

PY := .venv/bin/python
PROJECT ?=

help:
	@echo "Power BI Analyzer development commands"
	@echo ""
	@echo "  make check                 Check Ubuntu prerequisites"
	@echo "  make setup                 Create .venv and install dependencies"
	@echo "  make compile               Compile-check Python sources"
	@echo "  make test                  Run unit/regression tests"
	@echo "  make fixtures              Regenerate synthetic validation fixtures"
	@echo "  make validate              Run synthetic validation suite"
	@echo "  make db-up                 Start disposable MariaDB"
	@echo "  make db-down               Stop disposable MariaDB"
	@echo "  make db-reset              Recreate MariaDB from synthetic seed"
	@echo "  make analyze PROJECT=...   Analyze a PBIP project"
	@echo ""

check:
	./scripts/check-prereqs.sh

setup:
	./scripts/setup.sh

compile:
	$(PY) -m compileall -q pbi_usage_analyzer tests tools

test:
	$(PY) -m unittest discover -s tests -v

fixtures:
	$(PY) tools/validation/generate_validation_suite.py tools/validation/validation_suite --clean

validate:
	$(PY) tools/validation/validate_analyzer.py . tools/validation/validation_suite

db-up:
	./scripts/integration-up.sh

db-down:
	./scripts/integration-down.sh

db-reset:
	./scripts/integration-reset.sh

analyze:
	@if [ -z "$(PROJECT)" ]; then \
		echo "Usage: make analyze PROJECT=/path/to/PBIP/project"; \
		exit 1; \
	fi
	$(PY) ./run_analyzer.py "$(PROJECT)"

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
