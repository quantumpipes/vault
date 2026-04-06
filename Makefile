.PHONY: install lint format typecheck test test-all clean

install:
	pip install -e ".[sqlite,cli,fastapi,integrity,dev]"

lint:
	ruff check src/ tests/

format:
	ruff check --fix src/ tests/

typecheck:
	mypy src/qp_vault/

test:
	pytest tests/ -v --tb=short --cov=qp_vault --cov-report=term-missing

test-all: lint typecheck test

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
