"""Gives an agent the tools of every registered MCP server, as one set.

The gateway runs inside the API, and the agent reaches the servers only
through it: the chat calls it, and outside agents reach it at /api/mcp
(app/api/mcp.py). Each tool is listed as
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

from app.control.audit import EventSink, LogEventSink
from app.control.envelope import Action, Direction, Envelope
from app.control.guards.loop import LoopGuard
from app.control.guards.sensitive_data import scrub
from app.control.layer import ControlLayer
from app.control.pipeline import Decision

logger = logging.getLogger("app.control.mcp")

SEPARATOR = "__"
# A server that doesn't answer in time is left out of the tool list, so one
# slow server doesn't hang every agent.
LIST_TIMEOUT = 10
# Like the chat adapter, the messages don't say why: the reasons are in the
# logs, under the trace id.
BLOCKED_CALL = "The call to {tool} was blocked."
WITHHELD = "This tool result was withheld."
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
        sink: EventSink | None = None,
    ) -> None:
        self.layer = layer
        self.connect = connect
        # The enabled servers, read on every request, so a server added in
        # the Control tab shows up without a restart.
        self.servers = servers
        self.sink = sink or LogEventSink(logger)
        # Whether the loop guard blocked a call. A loop doesn't end by
        # itself, so the agent stops asking for tools.
        self.looping = False

    async def list_tools(self) -> list[types.Tool]:
        tools = []
        for server in await self.servers():
            try:
                upstream = await list_upstream_tools(server, self.connect)
            except Exception as exc:
                logger.warning(
                    "can't list the tools of %s: %s", server.name, scrub(repr(exc))
                )
                continue
            for tool in upstream:
                name = f"{server.name}{SEPARATOR}{tool.name}"
                tools.append(tool.model_copy(update={"name": name}))
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        agent_id: str,
        trace_id: str | None = None,
    ) -> types.CallToolResult:
        """Runs one tool call through the guards. Pass the trace id of the
        chat that asked for it, so the call shows up in that trace."""
        server_name, _, tool = name.partition(SEPARATOR)
        servers = {server.name: server for server in await self.servers()}
        server = servers.get(server_name)
        if server is None or not tool:
            return error(UNKNOWN_TOOL.format(tool=name))

        trace_id = trace_id or uuid4().hex
        await self.log(
            trace_id,
            "request",
            agent_id=agent_id,
            server=server.name,
            tool=tool,
            arguments=arguments,
        )
        inbound = Envelope(
            Direction.INBOUND, agent_id, server.name, tool, arguments, trace_id
        )
        decision = await self.inspect(inbound)
        if decision.action is Action.BLOCK:
            self.looping |= decision.verdicts[-1].guard == LoopGuard.name
            return await self.respond(
                trace_id, tool, error(BLOCKED_CALL.format(tool=name))
            )

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
        decision = await self.inspect(outbound)
        if decision.action is Action.BLOCK:
            return await self.respond(
                trace_id, tool, error(WITHHELD), done=not result.is_error
            )

        checked = iter(decision.envelope.payload["content"])
        content = [
            types.TextContent(type="text", text=next(checked))
            if isinstance(block, types.TextContent)
            else block
            for block in result.content
        ]
        return await self.respond(
            trace_id,
            tool,
            types.CallToolResult(
                content=content,
                structured_content=decision.envelope.payload.get("structured_content"),
                is_error=result.is_error,
            ),
        )

    async def inspect(self, envelope: Envelope) -> Decision:
        decision = await self.layer.inspect(envelope)
        # What the layer did, next to the verdicts of its guards, as the chat
        # adapter logs it, so the dashboard reads both the same way.
        await self.log(
            envelope.trace_id,
            "decision",
            direction=envelope.direction,
            server=envelope.server,
            tool=envelope.tool,
            action=decision.action,
            **decision.blocker(),
        )
        return decision

    async def respond(
        self,
        trace_id: str,
        tool: str,
        result: types.CallToolResult,
        done: bool | None = None,
    ) -> types.CallToolResult:
        """Logs the result the agent gets. done tells whether the server
        carried out the call, which a withheld result hides: by default,
        whether the result is not an error."""
        await self.log(
            trace_id,
            "response",
            tool=tool,
            done=not result.is_error if done is None else done,
            is_error=bool(result.is_error),
            body=result.model_dump(mode="json", exclude_none=True),
        )
        return result

    async def log(self, trace_id: str, stage: str, **data: Any) -> None:
        # Arguments and results are logged, but PII and secrets in them, as in
        # the chat's prompts, never reach the logs.
        payloads = ("arguments", "body")
        data = {k: scrub(v) if k in payloads else v for k, v in data.items()}
        await self.sink.write({"event": stage, "trace_id": trace_id, **data})
