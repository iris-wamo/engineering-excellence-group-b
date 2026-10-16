"""The two task event consumers: Redis Pub/Sub (fire-and-forget) and Redis Streams (durable).

Both hand events to the same TaskEventProcessor, so any difference in what they end up
processing comes from the transport alone.
"""

import asyncio
import logging
from typing import Any, Protocol, cast

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, ResponseError
from redis.typing import EncodableT, FieldT

from app.core.config import settings
from app.events.processor import TaskEventProcessor
from app.events.schemas import TaskEvent

logger = logging.getLogger(__name__)

PENDING_PAGE_SIZE = 100

# Stream replies as redis-py returns them over RESP2 with decode_responses=True.
StreamEntry = tuple[str, dict[str, str]]
XReadGroupReply = list[tuple[str, list[StreamEntry]]]


class PubSubTaskEventConsumer:
    """Subscribes to the task events channel.

    Redis delivers a Pub/Sub message only to the subscribers connected at that moment and
    keeps no copy. While this consumer is offline (or between a crash and reconnecting),
    events are dropped and cannot be recovered. A message that fails to process is gone too.
    """

    def __init__(self, redis: Redis, processor: TaskEventProcessor) -> None:
        self.redis = redis
        self.processor = processor
        self.channel = settings.task_events_channel

    async def run(self, stop: asyncio.Event, ready: asyncio.Event | None = None) -> None:
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(self.channel)
        logger.info("[pubsub] Subscribed to channel %s", self.channel)
        if ready is not None:
            ready.set()
        try:
            while not stop.is_set():
                message = await pubsub.get_message(timeout=0.5)
                if message is not None and message["type"] == "message":
                    await self.handle(message["data"])
        finally:
            try:
                await pubsub.unsubscribe(self.channel)
            except (RedisConnectionError, OSError):
                pass
            finally:
                await pubsub.aclose()
            logger.info("[pubsub] Unsubscribed from channel %s", self.channel)

    async def handle(self, raw: str) -> None:
        try:
            event = TaskEvent.model_validate_json(raw)
        except ValidationError:
            logger.error("[pubsub] Dropping malformed event: %s", raw)
            return
        try:
            await self.processor.process(event)
        except Exception:
            # Nothing to retry from: Pub/Sub has already forgotten the message.
            logger.exception("[pubsub] Failed to process event_id=%s; it is lost", event.event_id)


class StreamTaskEventConsumer:
    """Reads the task events stream as one member of a consumer group.

    The group remembers the last entry it delivered, so entries added while every consumer
    is offline are read when one comes back. An entry is acknowledged (XACK) only after it
    has been processed. If processing fails, or the consumer dies before XACK, the entry
    stays in the group's pending list and is delivered again later, which is why the
    processor must be idempotent. After `max_deliveries` attempts an entry is moved to the
    dead-letter stream so one bad event cannot block the rest forever.
    """

    def __init__(
        self,
        redis: Redis,
        processor: TaskEventProcessor,
        consumer_name: str,
        *,
        batch_size: int = 10,
        block_ms: int = 1000,
        reclaim_idle_ms: int = 30_000,
        max_deliveries: int = 5,
    ) -> None:
        self.redis = redis
        self.processor = processor
        self.consumer_name = consumer_name
        self.stream = settings.task_events_stream
        self.group = settings.task_events_stream_group
        self.dead_letter_stream = settings.task_events_dead_letter_stream
        self.batch_size = batch_size
        self.block_ms = block_ms
        self.reclaim_idle_ms = reclaim_idle_ms
        self.max_deliveries = max_deliveries

    async def ensure_group(self) -> None:
        """Create the consumer group at the start of the stream (id 0) if it does not exist.

        Starting at 0 rather than `$` means events published before the group existed are
        processed too.
        """
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
            logger.info("[streams] Created consumer group %s on %s", self.group, self.stream)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self, stop: asyncio.Event, ready: asyncio.Event | None = None) -> None:
        await self.ensure_group()
        logger.info(
            "[streams] Consumer %s joined group %s on %s",
            self.consumer_name,
            self.group,
            self.stream,
        )
        # Entries this consumer was given but never acknowledged before it last stopped.
        await self.retry_pending(min_idle_ms=0, only_mine=True)
        if ready is not None:
            ready.set()

        loop = asyncio.get_running_loop()
        next_reclaim = loop.time() + self.reclaim_idle_ms / 1000
        while not stop.is_set():
            try:
                await self.read_new()
                if loop.time() >= next_reclaim:
                    await self.retry_pending(min_idle_ms=self.reclaim_idle_ms)
                    next_reclaim = loop.time() + self.reclaim_idle_ms / 1000
            except ResponseError as exc:
                if "NOGROUP" not in str(exc):
                    raise
                logger.warning(
                    "[streams] Consumer group %s on %s is gone; recreating it",
                    self.group,
                    self.stream,
                )
                await self.ensure_group()
        logger.info("[streams] Consumer %s stopped", self.consumer_name)

    async def read_new(self, block_ms: int | None = None) -> int:
        """Read entries never delivered to this group (`>`), process and ack them."""
        response = cast(
            XReadGroupReply | None,
            await self.redis.xreadgroup(
                self.group,
                self.consumer_name,
                {self.stream: ">"},
                count=self.batch_size,
                block=self.block_ms if block_ms is None else block_ms,
            ),
        )
        handled = 0
        for _stream, entries in response or []:
            for entry_id, fields in entries:
                await self.handle_entry(entry_id, fields)
                handled += 1
        return handled

    async def retry_pending(self, min_idle_ms: int, only_mine: bool = False) -> int:
        """Claim every pending entry idle for at least `min_idle_ms` and process it again.

        Walks the pending list once, a page at a time, so a backlog larger than one page is
        recovered in a single call. Entries that fail again stay pending for the next call.
        """
        handled = 0
        start = "-"
        while True:
            page: list[dict[str, Any]] = await self.redis.xpending_range(  # type: ignore[assignment]
                self.stream,
                self.group,
                min=start,
                max="+",
                count=PENDING_PAGE_SIZE,
                consumername=self.consumer_name if only_mine else None,
                idle=min_idle_ms or None,
            )
            for item in page:
                if await self._retry_pending_entry(item, min_idle_ms):
                    handled += 1
            if len(page) < PENDING_PAGE_SIZE:
                return handled
            start = "(" + page[-1]["message_id"]  # exclusive: continue after the last one

    async def _retry_pending_entry(self, item: dict[str, Any], min_idle_ms: int) -> bool:
        """Claim one pending entry and process it. Returns False if there was nothing to do."""
        entry_id = item["message_id"]
        claimed = cast(
            list[tuple[str, dict[str, str] | None]],
            await self.redis.xclaim(
                self.stream, self.group, self.consumer_name, min_idle_ms, [entry_id]
            ),
        )
        fields = claimed[0][1] if claimed else None
        if not fields:
            if claimed or not await self.redis.xrange(self.stream, entry_id, entry_id):
                logger.warning(
                    "[streams] Pending entry %s was trimmed from the stream before it "
                    "was processed; its event is lost",
                    entry_id,
                )
                await self.redis.xack(self.stream, self.group, entry_id)
            return False
        attempt = item["times_delivered"] + 1
        logger.warning(
            "[streams] Redelivering pending entry %s (attempt %d, previously with %s)",
            entry_id,
            attempt,
            item["consumer"],
        )
        if attempt > self.max_deliveries:
            await self.dead_letter(entry_id, fields, f"exceeded {self.max_deliveries} attempts")
        else:
            await self.handle_entry(entry_id, fields)
        return True

    async def handle_entry(self, entry_id: str, fields: dict[str, str]) -> None:
        try:
            event = TaskEvent.model_validate_json(fields["payload"])
        except (KeyError, ValidationError):
            await self.dead_letter(entry_id, fields, "malformed payload")
            return
        try:
            await self.processor.process(event)
        except Exception:
            logger.exception(
                "[streams] Failed to process entry %s event_id=%s; left pending for retry",
                entry_id,
                event.event_id,
            )
            return
        await self.redis.xack(self.stream, self.group, entry_id)
        logger.debug("[streams] Acked entry %s", entry_id)

    async def dead_letter(self, entry_id: str, fields: dict[str, str], reason: str) -> None:
        """Copy the entry to the dead-letter stream and ack it, so it stops being retried."""
        entry: dict[FieldT, EncodableT] = {key: value for key, value in fields.items()}
        entry.update(source_entry_id=entry_id, reason=reason)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.xadd(self.dead_letter_stream, entry)
            pipe.xack(self.stream, self.group, entry_id)
            await pipe.execute()
        logger.error("[streams] Dead-lettered entry %s: %s", entry_id, reason)


class TaskEventConsumer(Protocol):
    async def run(self, stop: asyncio.Event, ready: asyncio.Event | None = None) -> None: ...


async def run_until_stopped(
    consumer: TaskEventConsumer, stop: asyncio.Event, retry_delay: float = 2.0
) -> None:
    """Run the consumer until `stop` is set, restarting it after any Redis error.

    A lost connection, Redis refusing writes (OOM, read-only replica), or any other Redis
    error is logged and retried after `retry_delay` seconds. A long-running worker should
    wait for Redis to recover, not exit and leave events unprocessed.
    """
    while not stop.is_set():
        try:
            await consumer.run(stop)
        except (RedisError, OSError):
            logger.exception("Consumer stopped on a Redis error; restarting in %ss", retry_delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=retry_delay)
            except TimeoutError:
                pass
