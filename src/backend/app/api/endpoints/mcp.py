from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import APIRouter
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.api.deps import mcp_gateway
from app.control.adapters.mcp_gateway import AGENT_HEADER, build_server
from app.core.config import settings

server = build_server(mcp_gateway)


def identity(scope: Scope) -> str | None:
    """The identity of the agent whose bearer token the request carries."""
    scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    for known, agent in settings.agent_identities.items():
        if compare_digest(token, known):
            return agent
    return None


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
        agent = identity(scope)
        if agent is None:
            response = JSONResponse(
                {"detail": "A valid agent token is required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        # The gateway reads the caller from this header. Set it from the
        # token, so an agent can't claim another identity.
        header = AGENT_HEADER.encode()
        headers = [(k, v) for k, v in scope["headers"] if k.lower() != header]
        scope = {**scope, "headers": [*headers, (header, agent.encode())]}
        await self.manager.handle_request(scope, receive, send)


endpoint = McpEndpoint()

router = APIRouter()
# A Starlette Route takes an ASGI app as its endpoint; FastAPI's add_route is
# typed for request handlers only.
router.routes.append(
    Route("/mcp", endpoint, methods=["GET", "POST", "DELETE"], include_in_schema=False)
)
