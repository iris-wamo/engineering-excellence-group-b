import asyncio
import logging

import pytest
from pydantic import RedisDsn
from redis.asyncio import Redis

from app.core.config import settings
from app.db.redis import close_redis_client
from app.events import publisher as publisher_module
from app.events.publisher import TaskEventPublisher, publish_task_events
from app.events.schemas import TaskEvent, TaskEventType
from tests.fixtures.events import make_event, stream_entries, stream_events


async def test_publish_appends_the_event_to_the_stream(redis_client: Redis) -> None:
    event = make_event()

    [result] = await TaskEventPublisher(redis_client).publish(event)

    assert await stream_events(redis_client) == [event]
    [(entry_id, fields)] = await stream_entries(redis_client)
    assert result.stream_entry_id == entry_id
    assert fields["event_type"] == "task.status_changed"


async def test_publish_reaches_connected_subscribers(redis_client: Redis) -> None:
    event = make_event(TaskEventType.assigned)
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(settings.task_events_channel)

    [result] = await TaskEventPublisher(redis_client).publish(event)
    message = None
    for _ in range(5):  # the first read consumes the (ignored) subscribe confirmation
        message = await pubsub.get_message(timeout=0.5)
        if message is not None:
            break
    await pubsub.aclose()

    assert result.pubsub_receivers == 1
    assert message is not None
    assert TaskEvent.model_validate_json(message["data"]) == event


async def test_pubsub_message_with_no_subscribers_is_dropped(redis_client: Redis) -> None:
    [result] = await TaskEventPublisher(redis_client).publish(make_event())

    assert result.pubsub_receivers == 0  # nobody got it, and Redis kept no copy
    assert len(await stream_events(redis_client)) == 1  # the stream still has it


async def test_publish_keeps_event_order(redis_client: Redis) -> None:
    events = [make_event(task_id=n) for n in range(5)]

    await TaskEventPublisher(redis_client).publish(*events)

    assert await stream_events(redis_client) == events


async def test_publish_task_events_logs_and_swallows_redis_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    unreachable = Redis(port=1, socket_connect_timeout=0.2)  # nothing listens on port 1
    monkeypatch.setattr(publisher_module, "get_redis_client", lambda: unreachable)

    with caplog.at_level(logging.ERROR, logger="app.events.publisher"):
        await asyncio.wait_for(publish_task_events([make_event()]), timeout=5)
    await unreachable.aclose()

    assert "Could not publish task events" in caplog.text


async def test_failed_xadd_is_reported_per_event_and_transport(
    redis_client: Redis, caplog: pytest.LogCaptureFixture
) -> None:
    await redis_client.set(settings.task_events_stream, "not a stream")  # XADD -> WRONGTYPE
    event = make_event()

    with caplog.at_level(logging.INFO, logger="app.events.publisher"):
        [result] = await TaskEventPublisher(redis_client).publish(event)

    assert result.stream_entry_id is None
    assert result.pubsub_receivers == 0  # PUBLISH still went through
    assert not result.fully_published
    assert f"event_id={event.event_id} task_id=1 to stream" in caplog.text
    assert "Published" not in caplog.text


async def test_unreachable_redis_costs_a_request_about_a_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-routable address: connecting hangs until the timeout instead of being refused.
    monkeypatch.setattr(settings, "redis_url", RedisDsn("redis://10.255.255.1:6379/0"))
    await close_redis_client()
    loop = asyncio.get_running_loop()

    started = loop.time()
    await publish_task_events([make_event()])
    elapsed = loop.time() - started
    await close_redis_client()

    assert elapsed < 3
