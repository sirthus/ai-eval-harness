.PHONY: install install-charts test test-cov lint check demo

install:
	pip install -e ".[dev]"

install-charts:
	pip install -e ".[dev,charts]"

test:
	pytest -q

test-cov:
	pytest tests/ --cov=harness --cov-report=term-missing -q

lint:
	ruff check .

check: lint test

demo:
	@echo "Rendering committed run_v1 report from local artifacts (no API call)."
	harness report --config configs/run_v1.yaml --run-id run_v1
	@echo
	@echo "Inspect the historical manifest: data/runs/run_v1.json"
	@echo "Inspect the markdown report:    reports/run_v1_report.md"
