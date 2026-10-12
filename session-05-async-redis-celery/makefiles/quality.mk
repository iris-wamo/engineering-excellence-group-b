.PHONY: format
format: ## Format code
	uv run ruff format .

.PHONY: lint
lint: ## Lint and typecheck
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

.PHONY: typecheck
typecheck: ## Run type checking
	uv run mypy .

.PHONY: lint-fix
lint-fix: ## Fix lint and format
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: hooks
hooks: ## Install pre-commit hooks
	uv run pre-commit install --config .pre-commit-config.yaml

.PHONY: hooks-run
hooks-run: ## Run all pre-commit hooks
	uv run pre-commit run --all-files
