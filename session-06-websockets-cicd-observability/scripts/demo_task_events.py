"""Demo 03 — Redis Pub/Sub vs Redis Streams, scripted end to end.

Run:  make events-demo   (or: uv run python -m scripts.demo_task_events)
Requires: docker compose up -d redis

Runs a Pub/Sub consumer and a Streams consumer in-process against the same events and
shows, step by step:
  1. both consumers online: both process the event
  2. both consumers offline: events published meanwhile
  3. both back online: Streams catches up on the backlog, Pub/Sub never sees it
  4. the same event published twice: neither consumer applies it twice
  5. a Streams worker that processes an entry but crashes before XACK: the entry is
     redelivered to another worker and skipped as a duplicate

Uses its own channel, stream, and keys (taskflow:demo:*), so it does not interfere with
consumers started by `make events-pubsub` / `make events-streams`.
"""

import asyncio
import logging
from typing import cast

from taskflow_shared.logging import configure_logging

from app.core.config import settings
from app.db.redis import create_redis_client
from app.events.consumers import (
    PubSubTaskEventConsumer,
    StreamTaskEventConsumer,
    XReadGroupReply,
)
from app.events.processor import TaskEventProcessor
from app.events.publisher import TaskEventPublisher
from app.events.schemas import TaskEvent, TaskEventType

logger = logging.getLogger("demo")

settings.task_events_channel = "taskflow:demo:task-events"
settings.task_events_stream = "taskflow:demo:task-events:stream"
settings.task_events_dead_letter_stream = "taskflow:demo:task-events:dead-letter"


def event(event_type: TaskEventType, task_id: int, **data: object) -> TaskEvent:
    return TaskEvent(
        event_type=event_type,
        task_id=task_id,
        workspace_id=1,
        project_id=1,
        actor_id=7,
        data=dict(data),
    )


def step(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


class Consumers:
    """Starts and stops both consumers as background tasks."""

    def __init__(self, pubsub: PubSubTaskEventConsumer, streams: StreamTaskEventConsumer):
        self.pubsub = pubsub
        self.streams = streams
        self.stop = asyncio.Event()
        self.tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self.stop = asyncio.Event()
        ready = [asyncio.Event(), asyncio.Event()]
        self.tasks = [
            asyncio.create_task(self.pubsub.run(self.stop, ready[0])),
            asyncio.create_task(self.streams.run(self.stop, ready[1])),
        ]
        await asyncio.gather(*(r.wait() for r in ready))

    async def drain_and_stop(self) -> None:
        await asyncio.sleep(1)  # let in-flight messages land
        self.stop.set()
        await asyncio.gather(*self.tasks)


async def main() -> None:
    redis = create_redis_client(socket_timeout=None)
    # Start from a clean slate so repeated runs print the same result.
    for pattern in ("taskflow:demo:*", "taskflow:events:demo:*"):
        for key in await redis.keys(pattern):
            await redis.delete(key)

    publisher = TaskEventPublisher(redis)
    pubsub_processor = TaskEventProcessor(redis, "demo:pubsub")
    streams_processor = TaskEventProcessor(redis, "demo:streams")
    consumers = Consumers(
        PubSubTaskEventConsumer(redis, pubsub_processor),
        StreamTaskEventConsumer(redis, streams_processor, "worker-a", block_ms=200),
    )

    step("1. Both consumers online")
    await consumers.start()
    first = event(
        TaskEventType.status_changed, 101, previous_status="todo", new_status="in_progress"
    )
    print(first.model_dump_json(indent=2), flush=True)
    await publisher.publish(first)
    await consumers.drain_and_stop()

    step("2. Both consumers offline: publishing 3 events")
    await publisher.publish(
        event(TaskEventType.assigned, 102, previous_assignee_id=None, new_assignee_id=8),
        event(TaskEventType.status_changed, 102, previous_status="todo", new_status="in_progress"),
        event(
            TaskEventType.status_changed, 101, previous_status="in_progress", new_status="review"
        ),
    )
    groups = await redis.xinfo_groups(settings.task_events_stream)
    logger.info(
        "Stream length=%d, group %s lag=%s (entries waiting to be read)",
        await redis.xlen(settings.task_events_stream),
        groups[0]["name"],
        groups[0]["lag"],
    )

    step("3. Both consumers back online")
    await consumers.start()
    await consumers.drain_and_stop()

    step("4. The same event (same event_id) published again")
    await consumers.start()
    await publisher.publish(first)
    await consumers.drain_and_stop()

    step("5. Streams worker processes an entry, then crashes before XACK")
    duplicate_target = event(
        TaskEventType.unassigned, 103, previous_assignee_id=8, new_assignee_id=None
    )
    await publisher.publish(duplicate_target)
    crashed = StreamTaskEventConsumer(redis, streams_processor, "worker-b")
    response = cast(
        XReadGroupReply,
        await redis.xreadgroup(
            crashed.group, crashed.consumer_name, {crashed.stream: ">"}, count=1
        ),
    )
    entry_id, fields = response[0][1][0]
    await streams_processor.process(TaskEvent.model_validate_json(fields["payload"]))
    logger.info("worker-b crashed before XACK of %s", entry_id)
    pending = await redis.xpending(crashed.stream, crashed.group)
    logger.info(
        "Pending entries in group: %d (owned by %s)", pending["pending"], pending["consumers"]
    )
    survivor = StreamTaskEventConsumer(redis, streams_processor, "worker-a")
    await survivor.retry_pending(min_idle_ms=0)
    pending = await redis.xpending(crashed.stream, crashed.group)
    logger.info("Pending entries in group after recovery: %d", pending["pending"])

    step("Result: events applied per consumer")
    pubsub_counts = await pubsub_processor.counts()
    streams_counts = await streams_processor.counts()
    print(f"{'event type':<22}{'pubsub':>8}{'streams':>9}")
    for event_type in TaskEventType:
        print(
            f"{event_type.value:<22}"
            f"{pubsub_counts.get(event_type.value, 0):>8}"
            f"{streams_counts.get(event_type.value, 0):>9}"
        )
    print(
        f"{'total':<22}{sum(pubsub_counts.values()):>8}{sum(streams_counts.values()):>9}"
        "   (5 distinct events; Pub/Sub was offline for 4 of them)"
    )
    await redis.aclose()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
