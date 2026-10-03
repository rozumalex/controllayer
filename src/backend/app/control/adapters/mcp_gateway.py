"""Gives an agent the tools of every registered MCP server, as one set.

The gateway runs inside the API, and the agent reaches the servers only
through it: nothing exposes it on its own URL. Each tool is listed as
`<server>__<tool>`. A call is checked before it reaches the server (inbound,
agent -> tool), and its result before the agent sees it (outbound, tool ->
agent). The agent id says whom the agent works for, so the guards can decide
what that user may see.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol
from uuid import uuid4

import anyio
import httpx2
import mcp_types as types
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.control.envelope import Action, Direction, Envelope
from app.control.layer import ControlLayer

logger = logging.getLogger("app.control.mcp")

SEPARATOR = "__"
# A server that doesn't answer in time is left out of the tool list, so one
# slow server doesn't hang every agent.
LIST_TIMEOUT = 10
# Like the chat adapter, the messages don't say why: the reasons are in the
# logs, under the trace id.
BLOCKED_CALL = "[control layer] The call to {tool} was blocked."
WITHHELD = "[control layer] This tool result was withheld."
UNKNOWN_TOOL = "Unknown tool: {tool}"


class UpstreamServer(Protocol):
    name: str
    url: str
    auth_header: str | None


Connect = Callable[[UpstreamServer], AbstractAsyncContextManager[Client]]


@asynccontextmanager
async def connect_http(server: UpstreamServer) -> AsyncIterator[Client]:
    """An MCP client session with a server over Streamable HTTP."""
    # TODO: the URL comes from a user, so the layer can be pointed at internal
    # addresses (SSRF). Block private networks before this is public.
    headers = {"Authorization": server.auth_header} if server.auth_header else None
    timeout = httpx2.Timeout(10, read=60)
    async with (
        create_mcp_http_client(headers=headers, timeout=timeout) as http,
        Client(streamable_http_client(server.url, http_client=http)) as client,
    ):
        yield client


async def list_upstream_tools(
    server: UpstreamServer, connect: Connect
) -> list[types.Tool]:
    with anyio.fail_after(LIST_TIMEOUT):
        async with connect(server) as client:
            return (await client.list_tools()).tools


def error(text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], is_error=True
    )


class McpGateway:
    def __init__(
        self,
        layer: ControlLayer,
        connect: Connect,
        servers: Callable[[], Awaitable[Sequence[UpstreamServer]]],
    ) -> None:
        self.layer = layer
        self.connect = connect
        # The enabled servers, read on every request, so a server added in
        # the Control tab shows up without a restart.
        self.servers = servers

    async def list_tools(self) -> list[types.Tool]:
        tools = []
        for server in await self.servers():
            try:
                upstream = await list_upstream_tools(server, self.connect)
            except Exception as exc:
                logger.warning("can't list the tools of %s: %r", server.name, exc)
                continue
            for tool in upstream:
                name = f"{server.name}{SEPARATOR}{tool.name}"
                tools.append(tool.model_copy(update={"name": name}))
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any], agent_id: str
    ) -> types.CallToolResult:
        server_name, _, tool = name.partition(SEPARATOR)
        servers = {server.name: server for server in await self.servers()}
        server = servers.get(server_name)
        if server is None or not tool:
            return error(UNKNOWN_TOOL.format(tool=name))

        trace_id = uuid4().hex
        inbound = Envelope(
            Direction.INBOUND, agent_id, server.name, tool, arguments, trace_id
        )
        decision = await self.layer.inspect(inbound)
        if decision.action is Action.BLOCK:
            return error(BLOCKED_CALL.format(tool=name))

        async with self.connect(server) as client:
            result = await client.call_tool(tool, decision.envelope.payload)

        # The guards see only the data: the text of each block and the
        # structured content, not the block types around them.
        texts = [b.text for b in result.content if isinstance(b, types.TextContent)]
        payload: dict[str, Any] = {"content": texts}
        if result.structured_content is not None:
            payload["structured_content"] = result.structured_content
        outbound = Envelope(
            Direction.OUTBOUND, agent_id, server.name, tool, payload, trace_id
        )
        decision = await self.layer.inspect(outbound)
        if decision.action is Action.BLOCK:
            return error(WITHHELD)

        checked = iter(decision.envelope.payload["content"])
        content = [
            types.TextContent(type="text", text=next(checked))
            if isinstance(block, types.TextContent)
            else block
            for block in result.content
        ]
        return types.CallToolResult(
            content=content,
            structured_content=decision.envelope.payload.get("structured_content"),
            is_error=result.is_error,
        )
