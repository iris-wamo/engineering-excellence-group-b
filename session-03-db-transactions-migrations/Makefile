.DEFAULT_GOAL := help

include makefiles/db.mk
include makefiles/quality.mk
include makefiles/testing.mk
include makefiles/docker.mk

.PHONY: help
help: ## List all available targets grouped by section
	@printf "Available commands:\n"
	@for file in $(MAKEFILE_LIST); do \
		if ! grep -q -E '^[a-zA-Z_-]+:.*?## .*$$' $$file; then continue; fi; \
		short_name=$$(basename $$file .mk); \
		if [ "$$short_name" = "Makefile" ]; then \
			section="General & Setup"; \
		elif [ "$$short_name" = "db" ]; then \
			section="Database & Migrations"; \
		elif [ "$$short_name" = "quality" ]; then \
			section="Code Quality & Linting"; \
		elif [ "$$short_name" = "testing" ]; then \
			section="Testing & Coverage"; \
		elif [ "$$short_name" = "docker" ]; then \
			section="Docker & Containerization"; \
		else \
			section="$$short_name"; \
		fi; \
		printf "\n\033[1;35m%s\033[0m:\n" "$$section"; \
		grep -E '^[a-zA-Z_-]+:.*?## .*$$' $$file | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'; \
	done

.PHONY: install
install: ## Install python version and all dependencies, and copy .env.example to .env
	uv sync
	@if [ ! -f .env ]; then \
		echo "Copying .env.example to .env..."; \
		cp .env.example .env; \
	fi

.PHONY: run
run: ## Start the FastAPI development server with reload
	uv run uvicorn app.main:app --reload
