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
