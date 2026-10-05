.PHONY: help check setup compile test validate validate-json check-fixtures check-runtime benchmark fixtures db-up db-down db-reset analyze clean

PY := .venv/bin/python
EXPORT ?=
PROJECT ?=

help:
	@echo "Power BI Analyzer development commands"
	@echo ""
	@echo "  make check                 Check Ubuntu prerequisites"
	@echo "  make setup                 Create .venv and install dependencies"
	@echo "  make compile               Compile-check Python sources"
	@echo "  make test                  Run unit/regression tests"
	@echo "  make check-runtime         Smoke-test runtime-only dependencies"
	@echo "  make benchmark             Time analysis of a large generated model"
	@echo "  make check-fixtures        Check generated fixture reproducibility"
	@echo "  make fixtures              Regenerate synthetic validation fixtures"
	@echo "  make validate              Run synthetic validation suite"
	@echo "  make validate-json EXPORT=... Validate a saved JSON export"
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
	$(PY) -m compileall -q pbi_usage_analyzer pbi_usage_analyzer_gui pbi_usage_analyzer_mcp tests tools

test:
	$(PY) -m unittest discover -s tests -v

check-runtime:
	$(PY) tools/validation/check_runtime.py

benchmark:
	$(PY) tools/validation/large_model.py

check-fixtures:
	$(PY) tools/validation/check_fixture_drift.py

fixtures:
	$(PY) tools/validation/generate_validation_suite.py tools/validation/validation_suite --clean

validate:
	$(PY) tools/validation/validate_analyzer.py . tools/validation/validation_suite

validate-json:
	@if [ -z "$(EXPORT)" ]; then \
		echo "Usage: make validate-json EXPORT=/path/to/analysis.json"; \
		exit 2; \
	fi
	$(PY) tools/validation/validate_json_export.py "$(EXPORT)"

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
