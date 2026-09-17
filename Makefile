.PHONY: install test lint format-check run

install:
	python -m pip install -e '.[dev,postgres]'

test:
	pytest

lint:
	ruff check .
	mypy apps domain_resolver

format-check:
	black --check .
	ruff format --check .

run:
	uvicorn apps.api.main:app --reload
