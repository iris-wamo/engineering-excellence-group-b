import asyncio

from pydantic import RedisDsn

from app.db.loop_clients import LoopClients
from app.db.redis import close_redis_client, get_redis_client
from tests.fixtures.redis import with_database


async def test_request_path_client_fails_fast() -> None:
    # redis-py's default retries 10 times with backoff, which held a request for ~24s
    # against an unreachable server. No connection is opened here.
    client = get_redis_client()
    pool_options = client.connection_pool.connection_kwargs

    retry = client.get_retry()
    assert retry is not None and retry.get_retries() == 0
    assert pool_options["socket_connect_timeout"] == 1
    assert pool_options["socket_timeout"] == 1
    await close_redis_client()


def test_loop_clients_drop_clients_of_closed_loops() -> None:
    clients: LoopClients[object] = LoopClients(object)
    old_loop = asyncio.new_event_loop()
    old_client = clients.get(old_loop)
    old_loop.close()

    new_loop = asyncio.new_event_loop()
    try:
        clients.get(new_loop)
        assert clients.pop(old_loop) is None  # forgotten once its loop closed
        assert clients.get(new_loop) is not old_client
    finally:
        new_loop.close()


def test_with_database_replaces_only_the_database_number() -> None:
    url = RedisDsn("redis://user:secret@cache.internal:6380/0?protocol=3")

    assert str(with_database(url, 15)) == "redis://user:secret@cache.internal:6380/15?protocol=3"


def test_with_database_adds_a_database_to_a_url_without_one() -> None:
    assert str(with_database(RedisDsn("redis://localhost:6379"), 15)) == (
        "redis://localhost:6379/15"
    )
