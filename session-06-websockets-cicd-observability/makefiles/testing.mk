.PHONY: test
test: ## Run the full test suite (unit, integration, auth)
	uv run pytest

.PHONY: test-unit
test-unit: ## Run unit tests only (no database needed)
	uv run pytest -m unit

.PHONY: test-integration
test-integration: ## Run integration tests (needs PostgreSQL, MongoDB and Redis)
	uv run pytest -m integration

.PHONY: test-auth
test-auth: ## Run auth tests (needs PostgreSQL and MongoDB)
	uv run pytest -m auth

.PHONY: test-cov
test-cov: ## Run the full test suite with coverage
	uv run pytest --cov=app --cov-report=term-missing
