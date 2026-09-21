.PHONY: install-dev format lint format-check test check pre-commit-install

install-dev:
	python3 -m pip install -e ".[dev]"

format:
	python3 -m ruff check --fix .
	python3 -m ruff format .

lint:
	python3 -m ruff check .

format-check:
	python3 -m ruff format --check .

test:
	python3 -m pytest --cov=code_harness --cov-report=term-missing

check: lint format-check test

pre-commit-install:
	python3 -m pre_commit install
