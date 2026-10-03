"""The MCP gateway as an MCP server, for agents outside Portcullis, such as
Claude Code or Cursor.

It is mounted at /api/mcp and takes the session token from sign-in, the same
token as the rest of the API. A client without one learns from the 401 how to
sign the user in with OAuth, see app/api/oauth.py. Each request works for the
user that token signs in: it lists only the tools their role allows, and
calls a tool through the gateway, with every guard of their policy, so the
call shows up in the traces under their name.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

import mcp_types as types
from fastapi import HTTPException
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.api.deps import current_user, mcp_gateway, tool_access, user_policy
from app.api.oauth import resource_metadata_url
from app.control.adapters.mcp_gateway import McpGateway

# The agent id of every call, so the traces show it came from an outside
# agent, not the assistant.
AGENT_ID = "mcp-client"


@dataclass(frozen=True)
class Caller:
    """The gateway of the user who sent the request, and whether their role
    allows a tool, by its gateway name."""

    gateway: McpGateway
    allows: Callable[[str], bool]


# Set for each request alone, so no two users ever share a gateway.
caller: ContextVar[Caller] = ContextVar("caller")


async def list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    """The user's tools: a tool their role blocks is never listed."""
    user = caller.get()
    tools = await user.gateway.list_tools()
    return types.ListToolsResult(tools=[t for t in tools if user.allows(t.name)])


async def call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult:
    """One call through the guards, as a trace of its own."""
    return await caller.get().gateway.call_tool(
        params.name, dict(params.arguments or {}), AGENT_ID, uuid4().hex
    )


server = Server(
    "portcullis",
    instructions=(
        "The tools your role at your organization allows, through Portcullis. "
        "Every call is checked against your role's policy and recorded."
    ),
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


class GatewayMcpApp:
    """The server over Streamable HTTP, as an ASGI app for the API to mount.

    A session manager runs only once, and the API starts again in each test,
    so every start makes a new one.
    """

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        server.streamable_http_app(
            # Stateless, so each request carries its own token and nothing
            # outlives it.
            stateless_http=True,
            json_response=True,
            # The token guards it, and the Host differs between Compose and
            # production.
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
        async with server.session_manager.run():
            yield

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            user = await current_user(Headers(scope=scope).get("authorization"))
        except HTTPException as exc:
            metadata = resource_metadata_url(HTTPConnection(scope))
            challenge = f'Bearer resource_metadata="{metadata}"'
            response = JSONResponse(
                {"detail": exc.detail}, exc.status_code, {"WWW-Authenticate": challenge}
            )
            await response(scope, receive, send)
            return
        policy = await user_policy(user)
        gateway = await mcp_gateway(user, policy)
        caller.set(Caller(gateway, tool_access(policy).allows))
        await server.session_manager.handle_request(scope, receive, send)


gateway_mcp_app = GatewayMcpApp()
