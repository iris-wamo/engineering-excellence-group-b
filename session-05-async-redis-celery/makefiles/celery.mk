.PHONY: celery-worker
celery-worker: ## Start Celery worker locally
	uv run celery -A app.core.celery_app worker -l info

.PHONY: celery-beat
celery-beat: ## Start Celery Beat periodic scheduler locally
	uv run celery -A app.core.celery_app beat -l info

.PHONY: flower
flower: ## Start Flower dashboard locally on port 5555
	uv run celery -A app.core.celery_app flower --port=5555

.PHONY: celery-demo
celery-demo: ## Run end-to-end Celery jobs demonstration (success, retry, idempotency, failure)
	uv run python -m scripts.demo_celery_jobs

.PHONY: beat-demo
beat-demo: ## Run end-to-end Celery Beat due reminders, overlap prevention & Flower demo
	uv run python -m scripts.demo_celery_beat
