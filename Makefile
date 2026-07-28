.PHONY: dev install test lint coverage selfplay web

install:
	cd server && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"

dev:
	cd server && .venv/bin/uvicorn app.main:app --reload

web:
	python3 -m http.server 5500

test:
	cd server && .venv/bin/pytest

coverage:
	cd server && .venv/bin/pytest --cov --cov-report=term-missing

lint:
	cd server && .venv/bin/ruff check .

selfplay:
	cd server && .venv/bin/python -m app.engine.cli
