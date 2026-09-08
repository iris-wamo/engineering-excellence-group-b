.PHONY: db-shell
db-shell: ## Open DB shell
	psql "postgresql://taskflow:taskflow@localhost:5432/taskflow"

.PHONY: migrate
migrate: ## Run migrations
	uv run alembic upgrade head

.PHONY: migrate-check
migrate-check: ## Check migrations status
	uv run alembic check

.PHONY: migrate-create
migrate-create: ## Create new migration (usage: make migrate-create m="message")
	@if [ -z "$(m)" ]; then \
		echo "Error: Please specify a message. Example: make migrate-create m=\"add new table\""; \
		exit 1; \
	fi
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: migrate-current
migrate-current: ## Show current migration
	uv run alembic current

.PHONY: migrate-history
migrate-history: ## Show migration history
	uv run alembic history

.PHONY: seed
seed: ## Seed database with default demo dataset (~200 tasks)
	uv run python scripts/seed_data.py --reset

.PHONY: seed-large
seed-large: ## Seed database with 10k tasks for query-performance benchmarking
	uv run python scripts/seed_data.py --reset --tasks 10000 --users 100 --projects 25

.PHONY: seed-huge
seed-huge: ## Seed database with 50k tasks for heavy stress testing
	uv run python scripts/seed_data.py --reset --tasks 50000 --users 200 --projects 50

.PHONY: db-reset
db-reset: ## Reset database tables and re-seed with default demo data
	uv run python scripts/seed_data.py --reset



