PYTHON ?= python3

.PHONY: verify
verify:
	$(PYTHON) -m ruff check census ingest tests
	$(PYTHON) -m pytest -q --cov --cov-report=term-missing
