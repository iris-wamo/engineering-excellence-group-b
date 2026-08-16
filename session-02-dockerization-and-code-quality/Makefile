.DEFAULT_GOAL := help

include makefiles/db.mk
include makefiles/quality.mk
include makefiles/testing.mk

.PHONY: help
help: ## List all available targets in alphabetical order
	@echo "Available commands:"
	@grep -h -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

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
