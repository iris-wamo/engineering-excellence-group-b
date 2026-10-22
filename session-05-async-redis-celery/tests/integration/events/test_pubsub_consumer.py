import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import ConnectionError as RedisConnectionError

from app.events.consumers import PubSubTaskEventConsumer
from app.events.processor import TaskEventProcessor
from app.events.publisher import TaskEventPublisher
from tests.fixtures.events import make_event

Online = Callable[[], Awaitable[None]]


@pytest.fixture()
def processor(redis_client: Redis) -> TaskEventProcessor:
    return TaskEventProcessor(redis_client, consumer_name="pubsub")


@pytest.fixture()
async def go_online(
    redis_client: Redis, processor: TaskEventProcessor
) -> AsyncGenerator[Online, None]:
    """Start the Pub/Sub consumer in the background; it is stopped after the test."""
    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    async def _start() -> None:
        ready = asyncio.Event()
        consumer = PubSubTaskEventConsumer(redis_client, processor)
        tasks.append(asyncio.create_task(consumer.run(stop, ready)))
        await asyncio.wait_for(ready.wait(), timeout=2)

    yield _start
    stop.set()
    await asyncio.gather(*tasks)


async def _wait_for_count(processor: TaskEventProcessor, expected: int) -> None:
    for _ in range(50):
        if sum((await processor.counts()).values()) >= expected:
            return
        await asyncio.sleep(0.02)


async def test_online_consumer_processes_published_events(
    redis_client: Redis, processor: TaskEventProcessor, go_online: Online
) -> None:
    await go_online()
    event = make_event(task_id=7)

    await TaskEventPublisher(redis_client).publish(event)
    await _wait_for_count(processor, 1)

    assert await processor.counts() == {"task.status_changed": 1}
    [entry] = await processor.timeline(7)
    assert entry["event_id"] == str(event.event_id)


async def test_events_published_while_offline_are_lost(
    redis_client: Redis, processor: TaskEventProcessor, go_online: Online
) -> None:
    await TaskEventPublisher(redis_client).publish(make_event(), make_event())

    await go_online()
    await TaskEventPublisher(redis_client).publish(make_event())
    await _wait_for_count(processor, 1)
    await asyncio.sleep(0.1)

    # Only the event sent after subscribing arrived; the earlier two are gone for good.
    assert await processor.counts() == {"task.status_changed": 1}


async def test_same_event_published_twice_is_applied_once(
    redis_client: Redis, processor: TaskEventProcessor, go_online: Online
) -> None:
    await go_online()
    event = make_event(task_id=7)
    second = make_event(task_id=7)

    await TaskEventPublisher(redis_client).publish(event, event, second)
    await _wait_for_count(processor, 2)
    await asyncio.sleep(0.1)

    assert await processor.counts() == {"task.status_changed": 2}
    assert [e["event_id"] for e in await processor.timeline(7)] == [
        str(event.event_id),
        str(second.event_id),
    ]


async def test_malformed_message_is_dropped_without_stopping_the_consumer(
    redis_client: Redis, processor: TaskEventProcessor, go_online: Online
) -> None:
    await go_online()

    await redis_client.publish(PubSubTaskEventConsumer(redis_client, processor).channel, "{bad")
    await TaskEventPublisher(redis_client).publish(make_event())
    await _wait_for_count(processor, 1)

    assert await processor.counts() == {"task.status_changed": 1}


async def test_connection_is_closed_even_when_unsubscribe_fails(
    redis_client: Redis, processor: TaskEventProcessor, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[PubSub] = []
    original_aclose = PubSub.aclose

    async def connection_lost(self: PubSub, *args: object, **kwargs: object) -> None:
        raise RedisConnectionError("connection lost")

    async def tracking_aclose(self: PubSub) -> None:
        closed.append(self)
        await original_aclose(self)

    monkeypatch.setattr(PubSub, "get_message", connection_lost)
    monkeypatch.setattr(PubSub, "unsubscribe", connection_lost)
    monkeypatch.setattr(PubSub, "aclose", tracking_aclose)

    with pytest.raises(RedisConnectionError):
        await PubSubTaskEventConsumer(redis_client, processor).run(asyncio.Event())

    assert len(closed) == 1
