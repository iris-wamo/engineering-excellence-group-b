.PHONY: docker-db-shell
docker-db-shell: ## Open a psql shell inside the Postgres container (uses its POSTGRES_USER / POSTGRES_DB)
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

.PHONY: docker-build
docker-build: ## Build the Docker images for every Compose service with a build section
	docker compose build

.PHONY: docker-up
docker-up: ## Start every Compose service in the background
	docker compose up -d

.PHONY: docker-down
docker-down: ## Stop and remove every Compose container (named volumes are kept)
	docker compose down

.PHONY: docker-logs
docker-logs: ## Follow one service's logs (default api; usage: make docker-logs s=redis)
	docker compose logs -f $(or $(s),api)

.PHONY: docker-shell
docker-shell: ## Open shell inside API container
	docker compose exec api sh

.PHONY: redis-cli
redis-cli: ## Open a redis-cli shell on the Dockerized Redis
	docker compose exec redis redis-cli
