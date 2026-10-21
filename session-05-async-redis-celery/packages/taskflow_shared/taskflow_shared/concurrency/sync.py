"""Run coroutines from synchronous code (e.g. Celery task bodies)."""

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    Safely handles cases where an event loop is already running in the current thread
    (such as during pytest-asyncio test runs) by running in a separate worker thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
