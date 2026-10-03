from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.api.deps import mcp_gateway
from app.control.adapters.mcp_gateway import build_server

server = build_server(mcp_gateway)


class McpEndpoint:
    """The gateway's Streamable HTTP endpoint, as a plain ASGI app."""

    manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        # A session manager runs only once, and tests start the app many
        # times, so each start gets a new one. Stateless with JSON responses:
        # every request stands alone, so any API replica can answer it.
        self.manager = StreamableHTTPSessionManager(
            server, stateless=True, json_response=True
        )
        async with self.manager.run():
            yield

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        assert self.manager is not None, "the app's lifespan starts the manager"
        await self.manager.handle_request(scope, receive, send)


endpoint = McpEndpoint()

router = APIRouter()
# A Starlette Route takes an ASGI app as its endpoint; FastAPI's add_route is
# typed for request handlers only.
router.routes.append(
    Route("/mcp", endpoint, methods=["GET", "POST", "DELETE"], include_in_schema=False)
)
