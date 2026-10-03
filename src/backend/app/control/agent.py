"""Lets the chat's model use the tools of the MCP servers behind the gateway.

The model gets every tool of every enabled server. When it asks for some, the
agent runs each call through the gateway, whose guards check the call before
the server sees it and the result before the model does, and sends the
results back to the model. It repeats until the model answers, at most
MAX_STEPS times. The calls go into the chat's trace, so the dashboard shows a
question and the tools it used together.
"""

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import mcp_types as types

from app.control.adapters.mcp_gateway import McpGateway
from app.control.adapters.openai_chat import ChatControl, arguments
from app.control.guards.sensitive_data import scrub

logger = logging.getLogger("app.control.agent")

# Model calls per question. The last one may not ask for tools, so the model
# answers with what it has.
MAX_STEPS = 6
# OpenAI refuses a request with more tools.
MAX_TOOLS = 128
FAILED = "[control layer] The call to {tool} failed."


def openai_tool(tool: types.Tool) -> dict[str, Any]:
    function = {"name": tool.name, "parameters": tool.input_schema}
    if tool.description:
        function["description"] = tool.description
    return {"type": "function", "function": function}


def result_text(result: types.CallToolResult) -> str:
    texts = [b.text for b in result.content if isinstance(b, types.TextContent)]
    if texts:
        return "\n".join(texts)
    if result.structured_content is not None:
        return json.dumps(result.structured_content)
    return ""


class Agent:
    def __init__(
        self,
        control: ChatControl,
        gateway: McpGateway,
        agent_id: str = "anonymous",
        allows: Callable[[str], bool] = lambda name: True,
    ) -> None:
        self.control = control
        self.gateway = gateway
        # Whether the user's policy lets them call a tool. The model never
        # sees the others; the gateway blocks them too, in case it asks.
        self.allows = allows
        # Whom the agent works for, so the guards can decide what they may
        # see. Everyone is anonymous until the app has users.
        self.agent_id = agent_id

    async def tools(self) -> list[dict[str, Any]]:
        tools = [
            openai_tool(tool)
            for tool in await self.gateway.list_tools()
            if self.allows(tool.name)
        ]
        if len(tools) > MAX_TOOLS:
            logger.warning(
                "%d tools, the model gets the first %d", len(tools), MAX_TOOLS
            )
        return tools[:MAX_TOOLS]

    def request(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], step: int
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"messages": messages}
        if tools:
            request["tools"] = tools
            if step == MAX_STEPS - 1:
                request["tool_choice"] = "none"
        return request

    async def run(self, call: dict[str, Any], trace_id: str) -> dict[str, Any]:
        """Runs one tool call through the gateway, as a tool message."""
        function = call.get("function", {})
        name = function.get("name", "")
        try:
            result = await self.gateway.call_tool(
                name, arguments(function), self.agent_id, trace_id
            )
            content = result_text(result)
        except Exception as exc:
            # A server that fails mid-call ends the call, not the chat.
            logger.warning(
                "tool %s failed: trace_id=%s %s", name, trace_id, scrub(repr(exc))
            )
            content = FAILED.format(tool=name)
        return {"role": "tool", "tool_call_id": call.get("id"), "content": content}

    async def complete(
        self, messages: list[dict[str, Any]], trace_id: str
    ) -> dict[str, Any]:
        tools = await self.tools()
        for step in range(MAX_STEPS):
            response = await self.control.complete(
                self.request(messages, tools, step), trace_id
            )
            choice = response["choices"][0]
            calls = choice["message"].get("tool_calls")
            if not calls or choice["finish_reason"] == "content_filter":
                break
            results = [await self.run(call, trace_id) for call in calls]
            messages = [*messages, choice["message"], *results]
        return response

    async def stream(
        self, messages: list[dict[str, Any]], trace_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Like complete, but yields the answer's chunks as the model writes
        them. The chunks that ask for tools are kept back: the agent runs
        the tools instead."""
        tools = await self.tools()
        for step in range(MAX_STEPS):
            content: list[str] = []
            calls: list[dict[str, Any]] = []
            async for part in self.control.stream(
                self.request(messages, tools, step), trace_id
            ):
                choice = part["choices"][0]
                delta = choice["delta"]
                if delta.get("tool_calls"):
                    calls = delta["tool_calls"]
                    continue
                content.append(delta.get("content") or "")
                yield part
            if not calls:
                return
            calls = [{k: v for k, v in c.items() if k != "index"} for c in calls]
            message = {"role": "assistant", "content": "".join(content)}
            results = [await self.run(call, trace_id) for call in calls]
            messages = [*messages, {**message, "tool_calls": calls}, *results]
