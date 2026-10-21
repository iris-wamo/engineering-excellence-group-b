.PHONY: celery-worker
celery-worker: ## Start Celery worker locally
	uv run celery -A app.core.celery_app worker -l info

.PHONY: celery-beat
celery-beat: ## Start Celery Beat periodic scheduler locally
	uv run celery -A app.core.celery_app beat -l info

.PHONY: flower
flower: ## Start Flower locally on 127.0.0.1 (port FLOWER_PORT, default 5555; login FLOWER_BASIC_AUTH if set)
	uv run celery -A app.core.celery_app flower --address=127.0.0.1 --port=$(or $(FLOWER_PORT),5555)

.PHONY: celery-demo
celery-demo: ## Run end-to-end Celery jobs demonstration (success, retry, idempotency, failure)
	uv run python -m scripts.demo_celery_jobs

.PHONY: beat-demo
beat-demo: ## Run end-to-end Celery Beat due reminders, overlap prevention & Flower demo
	uv run python -m scripts.demo_celery_beat
