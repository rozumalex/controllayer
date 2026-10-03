"""Gives an agent the tools of every registered MCP server, as one set.

The gateway runs inside the API, and the agent reaches the servers only
through it: the chat calls it, and outside agents reach it at /api/mcp
(app/api/mcp.py). Each tool is listed as `<server>__<tool>`. Each tool's
definition is checked before the model sees it, and a tool that fails is
hidden and refused. A call is checked before it reaches the server
(inbound, agent -> tool), and its result before the agent sees it
(outbound, tool -> agent). The agent id says whom the agent works for, so
the guards can decide what that user may see.
"""

import asyncio
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
from app.control.guards.tool_poisoning import PINNED, definition_hash
from app.control.layer import ControlLayer
from app.control.pipeline import Decision

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
    # The pinned hash of each tool's definition, by tool name.
    tool_pins: dict[str, str]


Connect = Callable[[UpstreamServer], AbstractAsyncContextManager[Client]]
# Saves a server's pins.
Pin = Callable[[UpstreamServer, dict[str, str]], Awaitable[None]]


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


def definition(tool: types.Tool) -> dict[str, Any]:
    """What the model reads of a tool."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }


def tool_pin(tool: types.Tool) -> str:
    return definition_hash(definition(tool))


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
        log_payloads: bool = False,
        sink: EventSink | None = None,
        pin: Pin | None = None,
    ) -> None:
        self.layer = layer
        self.connect = connect
        # The enabled servers, read on every request, so a server added in
        # the Control tab shows up without a restart.
        self.servers = servers
        self.log_payloads = log_payloads
        self.sink = sink or LogEventSink(logger)
        # Whether the loop guard blocked a call. A loop doesn't end by
        # itself, so the agent stops asking for tools.
        self.looping = False
        # Trusts a tool on first use: pins the definition of a tool that has
        # no pin yet, if it passed the guards.
        self.pin = pin
        # The tools the guards hid from the model, refused if it calls them.
        self.hidden: set[str] = set()

    async def list_tools(
        self, agent_id: str = "anonymous", trace_id: str | None = None
    ) -> list[types.Tool]:
        """The tools whose definitions pass the guards. Pass the trace id of
        the chat, so a hidden tool shows up in its trace."""
        trace_id = trace_id or uuid4().hex
        tools = []
        for server in await self.servers():
            try:
                upstream = await list_upstream_tools(server, self.connect)
            except Exception as exc:
                logger.warning(
                    "can't list the tools of %s: %s", server.name, scrub(repr(exc))
                )
                continue
            decisions = await asyncio.gather(
                *(self.check(server, tool, agent_id, trace_id) for tool in upstream)
            )
            pins = dict(server.tool_pins)
            for tool, decision in zip(upstream, decisions, strict=True):
                name = f"{server.name}{SEPARATOR}{tool.name}"
                if decision.action is Action.BLOCK:
                    self.hidden.add(name)
                    continue
                tools.append(tool.model_copy(update={"name": name}))
                if all(v.action is Action.ALLOW for v in decision.verdicts):
                    pins.setdefault(tool.name, tool_pin(tool))
            if self.pin and pins != server.tool_pins:
                await self.pin(server, pins)
        return tools

    async def check(
        self, server: UpstreamServer, tool: types.Tool, agent_id: str, trace_id: str
    ) -> Decision:
        """Runs a tool's definition, with its pin, through the guards."""
        payload = definition(tool)
        if pinned := server.tool_pins.get(tool.name):
            payload[PINNED] = pinned
        envelope = Envelope(
            Direction.DEFINITION, agent_id, server.name, tool.name, payload, trace_id
        )
        return await self.layer.inspect(envelope)

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
        if name in self.hidden:
            return error(BLOCKED_CALL.format(tool=name))

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
            return await self.respond(trace_id, error(BLOCKED_CALL.format(tool=name)))

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
            return await self.respond(trace_id, error(WITHHELD))

        checked = iter(decision.envelope.payload["content"])
        content = [
            types.TextContent(type="text", text=next(checked))
            if isinstance(block, types.TextContent)
            else block
            for block in result.content
        ]
        return await self.respond(
            trace_id,
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
        )
        return decision

    async def respond(
        self, trace_id: str, result: types.CallToolResult
    ) -> types.CallToolResult:
        await self.log(
            trace_id,
            "response",
            is_error=bool(result.is_error),
            body=result.model_dump(mode="json", exclude_none=True),
        )
        return result

    async def log(self, trace_id: str, stage: str, **data: Any) -> None:
        # Arguments and results may hold secrets, like prompts in the chat.
        payloads = ("arguments", "body")
        if not self.log_payloads:
            data = {k: v for k, v in data.items() if k not in payloads}
        # PII and secrets never reach the logs, even with the payloads.
        data = {k: scrub(v) if k in payloads else v for k, v in data.items()}
        await self.sink.write({"event": stage, "trace_id": trace_id, **data})
