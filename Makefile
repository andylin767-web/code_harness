.PHONY: install-dev format lint format-check test check pre-commit-install

install-dev:
	python3 -m pip install -r requirements-dev.txt

format:
	python3 -m ruff check --fix .
	python3 -m ruff format .

lint:
	python3 -m ruff check .

format-check:
	python3 -m ruff format --check .

test:
	python3 -m pytest

check: lint format-check test

pre-commit-install:
	python3 -m pre_commit install
