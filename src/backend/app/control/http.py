import asyncio
from typing import Any

import httpx


class SharedClient:
    """One httpx client for the whole process, so calls reuse open
    connections instead of a new TCP and TLS handshake each time.

    A client belongs to the event loop it first ran on, so a new loop, as in
    the tests, gets a new client."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.client: httpx.AsyncClient | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def get(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self.client is None or self.client.is_closed or self.loop is not loop:
            self.client = httpx.AsyncClient(**self.options)
            self.loop = loop
        return self.client

    async def aclose(self) -> None:
        if self.client is not None and self.loop is asyncio.get_running_loop():
            await self.client.aclose()
        self.client = None
        self.loop = None


# The client for OpenAI. The app closes it on shutdown.
OPENAI_HTTP = SharedClient(
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)
