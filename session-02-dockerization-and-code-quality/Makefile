.DEFAULT_GOAL := help

.PHONY: help
help: ## List all available targets in alphabetical order
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: db-shell
db-shell: ## Open an interactive PostgreSQL shell on the local Postgres (\q to quit)
	psql "postgresql://taskflow:taskflow@localhost:5432/taskflow"

.PHONY: docker-db-shell
docker-db-shell: ## Open a psql shell on the Dockerized Postgres (host port 5433)
	psql "postgresql://taskflow:taskflow@localhost:5433/taskflow"

.PHONY: format
format: ## Format Python code using Ruff
	uv run ruff format .

.PHONY: install
install: ## Install python version and all dependencies, and copy .env.example to .env
	uv sync
	@if [ ! -f .env ]; then \
		echo "Copying .env.example to .env..."; \
		cp .env.example .env; \
	fi

.PHONY: lint
lint: ## Lint and check formatting using Ruff
	uv run ruff check .
	uv run ruff format --check .

.PHONY: lint-fix
lint-fix: ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: migrate
migrate: ## Run database migrations to upgrade to head
	uv run alembic upgrade head

.PHONY: migrate-check
migrate-check: ## Check if alembic migrations are in sync with database models
	uv run alembic check

.PHONY: migrate-create
migrate-create: ## Generate a new alembic migration (usage: make migrate-create m="message")
	@if [ -z "$(m)" ]; then \
		echo "Error: Please specify a message. Example: make migrate-create m=\"add new table\""; \
		exit 1; \
	fi
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: migrate-current
migrate-current: ## Show current database migration revision
	uv run alembic current

.PHONY: migrate-history
migrate-history: ## Show database migration history list
	uv run alembic history

.PHONY: run
run: ## Start the FastAPI development server with reload
	uv run uvicorn app.main:app --reload

.PHONY: test
test: ## Run the pytest test suite
	uv run pytest

.PHONY: test-cov
test-cov: ## Run the pytest test suite with coverage report
	uv run pytest --cov=app --cov-report=term-missing

.PHONY: help db-shell docker-db-shell format install lint lint-fix migrate migrate-check migrate-create migrate-current migrate-history docker-build docker-up docker-down docker-logs docker-shell test

docker-build: ## Build Docker images
	docker compose build

docker-up: ## Start application and database
	docker compose up -d

docker-down: ## Stop application and database
	docker compose down

docker-logs: ## Show application logs
	docker compose logs -f api

docker-shell: ## Open shell inside API container
	docker compose exec api sh
