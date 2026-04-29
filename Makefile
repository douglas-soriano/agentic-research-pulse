VENV   := $(CURDIR)/backend/.venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

.PHONY: install
install: $(VENV)/bin/activate  ## Install all deps (app + test) in .venv

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install -q -e "$(CURDIR)/backend/.[test]"

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

.PHONY: test
test: install  ## Run unit tests (fast, no API key needed)
	cd backend && $(PYTEST) tests/unit -v

.PHONY: test-integration
test-integration: install  ## Run integration test (requires GEMINI_API_KEY)
	cd backend && $(PYTEST) tests/integration -v -m integration

.PHONY: test-all
test-all: install  ## Run all unit tests (same as test; use test-integration for e2e)
	cd backend && $(PYTEST) tests/ -v -m "not integration"

# ---------------------------------------------------------------------------
# RAGAS eval
# ---------------------------------------------------------------------------

.PHONY: eval
eval: install  ## Run RAGAS eval script (requires GEMINI_API_KEY)
	cd backend && $(PYTHON) scripts/eval.py

# ---------------------------------------------------------------------------
# Docker services
# ---------------------------------------------------------------------------

.PHONY: up
up:  ## Start Redis + ChromaDB in background
	docker compose up -d redis chroma

.PHONY: down
down:  ## Stop all Docker services
	docker compose down

.PHONY: dev
dev: up  ## Start full stack (backend + worker + frontend)
	docker compose up -d

.PHONY: logs
logs:  ## Tail backend + worker logs
	docker compose logs -f backend worker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

.PHONY: clean
clean:  ## Remove .venv and pytest cache
	rm -rf backend/.venv backend/.pytest_cache backend/__pycache__

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
