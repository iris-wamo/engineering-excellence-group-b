.PHONY: seed
seed: ## Seed database with default demo dataset (~200 tasks)
	uv run python scripts/seed_data.py --reset

.PHONY: seed-large
seed-large: ## Seed database with 10k tasks for query-performance benchmarking
	uv run python scripts/seed_data.py --reset --tasks 10000 --users 100 --projects 25

.PHONY: seed-huge
seed-huge: ## Seed database with 50k tasks for heavy stress testing
	uv run python scripts/seed_data.py --reset --tasks 50000 --users 200 --projects 50

.PHONY: seed-clean
seed-clean: ## Wipe / truncate all database tables leaving an empty schema (0 rows)
	uv run python scripts/seed_data.py --clean-only

.PHONY: seed-reset
seed-reset: ## Reset database tables and re-seed with default demo data
	uv run python scripts/seed_data.py --reset

.PHONY: db-clean
db-clean: seed-clean ## Alias for seed-clean

.PHONY: db-reset
db-reset: seed-reset ## Alias for seed-reset
