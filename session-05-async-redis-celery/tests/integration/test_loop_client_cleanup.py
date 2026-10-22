"""The app's per-loop Redis and Mongo clients leave no open sockets once closed on their loop.

Each test gets its own event loop, so the autouse fixtures close both clients before that
loop ends. Here the loops are driven by hand: one uses and closes the clients, the next
looks them up again, which drops anything still registered for the closed loop.
"""

import asyncio
import gc
import warnings

from app.db.mongo import close_mongo_client, get_mongo_client, get_raw_task_imports_collection
from app.db.redis import close_redis_client, get_redis_client


async def _use_then_close() -> None:
    await get_redis_client().ping()
    await get_raw_task_imports_collection().count_documents({})
    await close_redis_client()
    await close_mongo_client()


async def _next_loop_lookup() -> None:
    get_redis_client()
    get_mongo_client()
    await close_redis_client()
    await close_mongo_client()


def test_app_clients_closed_on_their_loop_leave_no_open_connection() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        asyncio.run(_use_then_close())
        asyncio.run(_next_loop_lookup())
        gc.collect()  # an unclosed client or socket warns when it is collected

    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []
