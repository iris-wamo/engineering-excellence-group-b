"""One client per running event loop, shared by the Mongo and Redis helpers.

asyncio clients (and their connection pools) are bound to the loop that created them, and
each pytest-asyncio test runs on its own loop. Clients of loops that have since closed are
dropped on the next lookup, so a loop that was never explicitly cleaned up is not kept alive.
"""

import asyncio
from collections.abc import Callable


class LoopClients[ClientT]:
    def __init__(self, factory: Callable[[], ClientT]) -> None:
        self._factory = factory
        self._clients: dict[asyncio.AbstractEventLoop, ClientT] = {}

    def get(self, loop: asyncio.AbstractEventLoop) -> ClientT:
        """Return the client for `loop`, creating it on first use."""
        for stale in [other for other in self._clients if other.is_closed()]:
            del self._clients[stale]
        client = self._clients.get(loop)
        if client is None:
            client = self._factory()
            self._clients[loop] = client
        return client

    def pop(self, loop: asyncio.AbstractEventLoop) -> ClientT | None:
        """Forget and return the client for `loop`, if there is one. The caller closes it."""
        return self._clients.pop(loop, None)
