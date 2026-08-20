.PHONY: test
test: ## Run tests
	uv run pytest

.PHONY: test-cov
test-cov: ## Run tests with coverage
	uv run pytest --cov=app --cov-report=term-missing
