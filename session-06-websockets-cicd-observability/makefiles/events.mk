.PHONY: events-pubsub
events-pubsub: ## Run the Redis Pub/Sub task event consumer (Ctrl+C to stop)
	uv run python -m scripts.task_event_consumer pubsub

.PHONY: events-streams
events-streams: ## Run the Redis Streams task event consumer (Ctrl+C to stop; optional NAME=worker-1)
	uv run python -m scripts.task_event_consumer streams $(if $(NAME),--name $(NAME))

.PHONY: events-demo
events-demo: ## Scripted Pub/Sub vs Streams demo: offline consumer, duplicates, crash recovery
	uv run python -m scripts.demo_task_events
