"""One client per running event loop, shared by the Mongo and Redis helpers.

asyncio clients (and their connection pools) are bound to the loop that created them, and
each pytest-asyncio test runs on its own loop. A client must be closed on its own loop,
before that loop ends (`LoopClients.close`): once the loop is closed, its async close can no
longer run. Clients of loops that closed without that are dropped on the next lookup with a
warning, since their connections then stay open until garbage collection.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class LoopClients[ClientT]:
    def __init__(
        self,
        factory: Callable[[], ClientT],
        close: Callable[[ClientT], Awaitable[None]],
    ) -> None:
        self._factory = factory
        self._close = close
        self._clients: dict[asyncio.AbstractEventLoop, ClientT] = {}

    def get(self, loop: asyncio.AbstractEventLoop) -> ClientT:
        """Return the client for `loop`, creating it on first use."""
        for stale in [other for other in self._clients if other.is_closed()]:
            dropped = self._clients.pop(stale)
            logger.warning(
                "Dropped a %s whose event loop closed before the client was closed; its "
                "connections stay open until garbage collection. Close it on its own loop.",
                type(dropped).__name__,
            )
        client = self._clients.get(loop)
        if client is None:
            client = self._factory()
            self._clients[loop] = client
        return client

    def pop(self, loop: asyncio.AbstractEventLoop) -> ClientT | None:
        """Forget and return the client for `loop`, if there is one. The caller closes it."""
        return self._clients.pop(loop, None)

    async def close(self, loop: asyncio.AbstractEventLoop) -> None:
        """Close and forget the client for `loop`, if there is one. Call it on that loop."""
        client = self.pop(loop)
        if client is not None:
            await self._close(client)
