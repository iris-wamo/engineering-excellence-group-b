.PHONY: docker-db-shell
docker-db-shell: ## Open a psql shell on the Dockerized Postgres (host port 5433)
	psql "postgresql://taskflow:taskflow@localhost:5433/taskflow"

.PHONY: docker-build
docker-build: ## Build Docker images
	docker compose build

.PHONY: docker-up
docker-up: ## Start application, Postgres, MongoDB, and Redis
	docker compose up -d

.PHONY: docker-down
docker-down: ## Stop application and database
	docker compose down

.PHONY: docker-logs
docker-logs: ## Show application logs
	docker compose logs -f api

.PHONY: docker-shell
docker-shell: ## Open shell inside API container
	docker compose exec api sh

.PHONY: redis-cli
redis-cli: ## Open a redis-cli shell on the Dockerized Redis
	docker compose exec redis redis-cli
