"""Publishes task events to Redis Pub/Sub and Redis Streams side by side.

Every event goes to both transports in one round trip so the two can be compared on the
same traffic: PUBLISH reaches only the subscribers connected right now, XADD appends the
event to a stream that consumer groups read at their own pace.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.db.redis import get_redis_client
from app.events.schemas import TaskEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishResult:
    """What happened to one event on each transport."""

    event: TaskEvent
    pubsub_receivers: int | None
    """Subscribers that got the Pub/Sub message (0: dropped). None if PUBLISH failed."""
    stream_entry_id: str | None
    """Id of the stream entry. None if XADD failed."""

    @property
    def fully_published(self) -> bool:
        return self.pubsub_receivers is not None and self.stream_entry_id is not None


class TaskEventPublisher:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, *events: TaskEvent) -> list[PublishResult]:
        """Send each event with XADD and PUBLISH in a single pipeline.

        A command that fails for one event does not hide what happened to the others:
        each result records both transports separately, and each failure is logged with
        the event and transport it hit. Raises RedisError only when Redis cannot be
        reached or the connection breaks.
        """
        if not events:
            return []

        pipe = self.redis.pipeline(transaction=False)
        for event in events:
            payload = event.model_dump_json()
            # The stream is the durable record and goes first; Pub/Sub is best effort.
            # The two are separate commands, so one can fail while the other succeeds;
            # the result and the log say which.
            pipe.xadd(
                settings.task_events_stream,
                {"event_type": event.event_type.value, "payload": payload},
                maxlen=settings.task_events_stream_maxlen,
                approximate=True,
            )
            pipe.publish(settings.task_events_channel, payload)
        replies = await pipe.execute(raise_on_error=False)

        results = []
        for event, entry_id, receivers in zip(events, replies[0::2], replies[1::2], strict=True):
            for transport, reply in (("stream", entry_id), ("pubsub", receivers)):
                if isinstance(reply, Exception):
                    logger.error(
                        "Could not publish %s event_id=%s task_id=%s to %s: %s",
                        event.event_type.value,
                        event.event_id,
                        event.task_id,
                        transport,
                        reply,
                    )
            result = PublishResult(
                event=event,
                pubsub_receivers=None if isinstance(receivers, Exception) else receivers,
                stream_entry_id=None if isinstance(entry_id, Exception) else entry_id,
            )
            if result.fully_published:
                logger.info(
                    "Published %s event_id=%s task_id=%s: pubsub_receivers=%d stream_entry=%s",
                    event.event_type.value,
                    event.event_id,
                    event.task_id,
                    result.pubsub_receivers,
                    result.stream_entry_id,
                )
            results.append(result)
        return results


async def publish_task_events(events: Sequence[TaskEvent]) -> None:
    """Best-effort publish, called after the database commit. Never raises.

    The task change is already committed, so a Redis outage must not turn a successful
    request into an error. The event is lost in that case; docs/session-05/
    redis-pubsub-vs-streams.md explains this dual-write gap and the outbox that closes it.
    """
    if not events:
        return
    try:
        await TaskEventPublisher(get_redis_client()).publish(*events)
    except (RedisError, OSError):
        # The pipeline failed as a whole (Redis unreachable, or the connection broke), so
        # it is unknown which events, if any, arrived. Failures of single commands are
        # logged per event and transport by publish() instead.
        logger.exception(
            "Could not publish task events %s",
            ", ".join(f"{e.event_type.value}:{e.event_id}" for e in events),
        )
