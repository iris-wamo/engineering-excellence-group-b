import asyncio
import logging
from typing import cast

import pytest
from redis.asyncio import Redis

from app.core.config import settings
from app.events.consumers import StreamTaskEventConsumer, XReadGroupReply
from app.events.processor import ProcessOutcome, TaskEventProcessor
from app.events.publisher import TaskEventPublisher
from app.events.schemas import TaskEvent, TaskEventType
from tests.fixtures.events import make_event, stream_entries


@pytest.fixture()
def processor(redis_client: Redis) -> TaskEventProcessor:
    return TaskEventProcessor(redis_client, consumer_name="streams")


def _consumer(
    redis: Redis, processor: TaskEventProcessor, name: str = "worker-a", **options: int
) -> StreamTaskEventConsumer:
    return StreamTaskEventConsumer(redis, processor, name, block_ms=50, **options)


async def _pending_count(redis: Redis) -> int:
    summary = await redis.xpending(settings.task_events_stream, settings.task_events_stream_group)
    return int(summary["pending"])


async def _read_without_ack(redis: Redis, consumer_name: str) -> tuple[str, TaskEvent]:
    """What a worker that crashes before XACK leaves behind: a delivered, pending entry."""
    reply = cast(
        XReadGroupReply,
        await redis.xreadgroup(
            settings.task_events_stream_group,
            consumer_name,
            {settings.task_events_stream: ">"},
            count=1,
        ),
    )
    entry_id, fields = reply[0][1][0]
    return entry_id, TaskEvent.model_validate_json(fields["payload"])


async def test_events_published_while_offline_are_processed_on_start(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    events = [make_event(TaskEventType.assigned), make_event(), make_event()]
    await TaskEventPublisher(redis_client).publish(*events)  # nobody is reading

    handled = await consumer.read_new()

    assert handled == 3
    assert await processor.counts() == {"task.assigned": 1, "task.status_changed": 2}
    assert await _pending_count(redis_client) == 0  # all acknowledged


async def test_group_created_after_publishing_still_sees_earlier_events(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    await TaskEventPublisher(redis_client).publish(make_event())
    consumer = _consumer(redis_client, processor)

    await consumer.ensure_group()
    await consumer.ensure_group()  # idempotent

    assert await consumer.read_new() == 1


async def test_entry_processed_but_not_acked_is_redelivered_and_skipped(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    survivor = _consumer(redis_client, processor)
    await survivor.ensure_group()
    await TaskEventPublisher(redis_client).publish(make_event(task_id=9))
    _, event = await _read_without_ack(redis_client, "worker-b")
    assert await processor.process(event) is ProcessOutcome.processed  # then worker-b dies

    redelivered = await survivor.retry_pending(min_idle_ms=0)

    assert redelivered == 1
    assert await processor.counts() == {"task.status_changed": 1}  # not 2
    assert len(await processor.timeline(9)) == 1
    assert await _pending_count(redis_client) == 0


async def test_restarted_consumer_retries_its_own_unacked_entries(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    await TaskEventPublisher(redis_client).publish(make_event())
    await _read_without_ack(redis_client, consumer.consumer_name)  # crashed before processing

    assert await consumer.retry_pending(min_idle_ms=0, only_mine=True) == 1
    assert await processor.counts() == {"task.status_changed": 1}
    assert await _pending_count(redis_client) == 0


async def test_republished_event_with_same_id_has_no_duplicate_effect(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    event = make_event(task_id=4)

    await TaskEventPublisher(redis_client).publish(event, event)  # two stream entries
    await consumer.read_new()

    assert await processor.counts() == {"task.status_changed": 1}
    assert len(await processor.timeline(4)) == 1
    assert await _pending_count(redis_client) == 0  # the duplicate is acked too


async def test_failed_processing_leaves_entry_pending_until_retry_succeeds(
    redis_client: Redis, processor: TaskEventProcessor, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    await TaskEventPublisher(redis_client).publish(make_event())

    async def broken(event: TaskEvent) -> ProcessOutcome:
        raise RuntimeError("downstream unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(processor, "process", broken)
        await consumer.read_new()
    assert await _pending_count(redis_client) == 1

    await consumer.retry_pending(min_idle_ms=0)

    assert await processor.counts() == {"task.status_changed": 1}
    assert await _pending_count(redis_client) == 0


async def test_entry_failing_too_often_is_dead_lettered(
    redis_client: Redis, processor: TaskEventProcessor, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _consumer(redis_client, processor, max_deliveries=2)
    await consumer.ensure_group()
    await TaskEventPublisher(redis_client).publish(make_event())

    async def broken(event: TaskEvent) -> ProcessOutcome:
        raise RuntimeError("always fails")

    monkeypatch.setattr(processor, "process", broken)
    await consumer.read_new()  # attempt 1
    await consumer.retry_pending(min_idle_ms=0)  # attempt 2
    await consumer.retry_pending(min_idle_ms=0)  # over the limit

    dead = await stream_entries(redis_client, settings.task_events_dead_letter_stream)
    assert len(dead) == 1
    assert dead[0][1]["reason"] == "exceeded 2 attempts"
    assert await _pending_count(redis_client) == 0


async def test_malformed_entry_is_dead_lettered_and_does_not_block_others(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    await redis_client.xadd(settings.task_events_stream, {"payload": "{not json"})
    await TaskEventPublisher(redis_client).publish(make_event())

    await consumer.read_new()

    assert await processor.counts() == {"task.status_changed": 1}
    dead = await stream_entries(redis_client, settings.task_events_dead_letter_stream)
    assert [fields["reason"] for _, fields in dead] == ["malformed payload"]
    assert await _pending_count(redis_client) == 0


async def test_consumer_recreates_a_deleted_group_and_keeps_consuming(
    redis_client: Redis, processor: TaskEventProcessor
) -> None:
    consumer = _consumer(redis_client, processor)
    stop, ready = asyncio.Event(), asyncio.Event()
    running = asyncio.create_task(consumer.run(stop, ready))
    await asyncio.wait_for(ready.wait(), timeout=2)

    await redis_client.delete(settings.task_events_stream)  # takes the group with it
    await asyncio.sleep(0.2)  # the next XREADGROUP fails with NOGROUP
    await TaskEventPublisher(redis_client).publish(make_event())
    for _ in range(50):
        if await processor.counts():
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(running, timeout=2)

    assert await processor.counts() == {"task.status_changed": 1}


async def test_pending_entry_trimmed_from_the_stream_is_reported(
    redis_client: Redis, processor: TaskEventProcessor, caplog: pytest.LogCaptureFixture
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    await TaskEventPublisher(redis_client).publish(make_event())
    entry_id, _ = await _read_without_ack(redis_client, "worker-b")
    await redis_client.xtrim(settings.task_events_stream, maxlen=0, approximate=False)

    with caplog.at_level(logging.WARNING, logger="app.events.consumers"):
        await consumer.retry_pending(min_idle_ms=0)

    assert f"Pending entry {entry_id} was trimmed" in caplog.text
    assert await _pending_count(redis_client) == 0
    assert await processor.counts() == {}


async def test_entry_claimed_by_another_consumer_is_not_reported_as_trimmed(
    redis_client: Redis,
    processor: TaskEventProcessor,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _consumer(redis_client, processor)
    await consumer.ensure_group()
    await TaskEventPublisher(redis_client).publish(make_event())
    await _read_without_ack(redis_client, "worker-b")

    async def lost_the_race(*args: object, **kwargs: object) -> list[object]:
        return []  # what XCLAIM answers when another consumer claimed the entry first

    monkeypatch.setattr(redis_client, "xclaim", lost_the_race)
    with caplog.at_level(logging.WARNING, logger="app.events.consumers"):
        handled = await consumer.retry_pending(min_idle_ms=0)

    assert handled == 0
    assert "trimmed" not in caplog.text
    assert await _pending_count(redis_client) == 1  # still worker-b's to finish


async def test_task_timeline_keeps_only_the_most_recent_entries(redis_client: Redis) -> None:
    processor = TaskEventProcessor(redis_client, "streams", timeline_limit=3)
    events = [make_event(task_id=5) for _ in range(5)]

    for event in events:
        await processor.process(event)

    assert [e["event_id"] for e in await processor.timeline(5)] == [
        str(e.event_id) for e in events[-3:]
    ]
    assert await processor.counts() == {"task.status_changed": 5}
