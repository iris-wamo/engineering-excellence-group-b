"""Run a task event consumer until Ctrl+C.

    uv run python -m scripts.task_event_consumer pubsub
    uv run python -m scripts.task_event_consumer streams [--name worker-1]

Run one of each in separate terminals, then change task statuses or assignments through
the API (or run `make events-demo`) and compare their logs. Stop a consumer, make more
changes, and start it again to see what each transport does with events sent while it
was offline. See docs/session-05/redis-pubsub-vs-streams.md.
"""

import argparse
import asyncio
import logging
import os
import signal
import socket

from taskflow_shared.logging import configure_logging

from app.db.redis import create_redis_client
from app.events.consumers import (
    PubSubTaskEventConsumer,
    StreamTaskEventConsumer,
    run_until_stopped,
)
from app.events.processor import TaskEventProcessor

logger = logging.getLogger("task_event_consumer")


async def main(mode: str, name: str) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    # No socket timeout: XREADGROUP BLOCK and Pub/Sub reads wait on purpose.
    redis = create_redis_client(socket_timeout=None)
    # Processor keys are per transport, not per worker: Streams workers in the same group
    # share one result set, just as they share the work.
    processor = TaskEventProcessor(redis, consumer_name=mode)
    consumer: PubSubTaskEventConsumer | StreamTaskEventConsumer = (
        PubSubTaskEventConsumer(redis, processor)
        if mode == "pubsub"
        else StreamTaskEventConsumer(redis, processor, consumer_name=name)
    )
    try:
        await run_until_stopped(consumer, stop)
    finally:
        await redis.aclose()
        logger.info("Consumer shut down")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["pubsub", "streams"])
    parser.add_argument(
        "--name",
        default=f"{socket.gethostname()}-{os.getpid()}",
        help=(
            "Consumer name within the Streams group. Defaults to <host>-<pid>, so two "
            "processes on one machine never share a name. Pass a fixed name to have a "
            "restarted worker retry its own unacknowledged entries immediately."
        ),
    )
    args = parser.parse_args()
    configure_logging()
    asyncio.run(main(args.mode, args.name))
