"""Unit tests for taskflow_shared.concurrency."""

import asyncio

from taskflow_shared.concurrency import run_async


async def _double(value: int) -> int:
    await asyncio.sleep(0)
    return value * 2


def test_run_async_without_a_running_loop() -> None:
    assert run_async(_double(21)) == 42


async def test_run_async_inside_a_running_loop() -> None:
    # asyncio.run would refuse here; run_async runs the coroutine on another thread
    assert run_async(_double(5)) == 10
