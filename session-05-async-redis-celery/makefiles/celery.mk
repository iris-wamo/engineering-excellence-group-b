.PHONY: celery-worker
celery-worker: ## Start Celery worker locally
	uv run celery -A app.core.celery_app worker -l info

.PHONY: celery-demo
celery-demo: ## Run end-to-end Celery jobs demonstration (success, retry, idempotency, failure)
	uv run python -m scripts.demo_celery_jobs

