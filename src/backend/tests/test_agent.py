import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client

from app.api.deps import control_layer
from app.control.adapters.mcp_gateway import UpstreamServer
from app.control.adapters.openai_chat import ChatControl
from app.control.agent import FAILED, MAX_STEPS, Agent
from app.control.guards.spotlight import OPEN
from app.control.upstream import MockUpstream, chunk, completion
from tests.test_mcp_gateway import INJECTION, calls, gateway

QUESTION = [{"role": "user", "content": "Who is client CLT-1?"}]


class ToolUsingUpstream(MockUpstream):
    """Asks for one tool call, then answers with the result it got. With
    always, it asks for the call every time."""

    def __init__(
        self, tool: str, arguments: dict[str, Any], always: bool = False
    ) -> None:
        super().__init__(delay=0)
        self.tool = tool
        self.arguments = arguments
        self.always = always
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        last = request["messages"][-1]
        if last["role"] == "tool" and not self.always:
            return completion("m", f"Answer: {last['content']}", "stop")
        response = completion("m", "", "tool_calls")
        response["choices"][0]["message"]["tool_calls"] = [
            {
                "id": f"call_{len(self.requests)}",
                "type": "function",
                "function": {
                    "name": self.tool,
                    "arguments": json.dumps(self.arguments),
                },
            }
        ]
        return response

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        message = (await self.complete(request))["choices"][0]["message"]
        for index, call in enumerate(message.get("tool_calls") or []):
            yield chunk("c", "m", {"tool_calls": [{"index": index, **call}]})
        if message.get("tool_calls"):
            yield chunk("c", "m", {}, "tool_calls")
            return
        yield chunk("c", "m", {"content": message["content"]})
        yield chunk("c", "m", {}, "stop")


class ListSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def agent(upstream: MockUpstream, sink: ListSink | None = None) -> Agent:
    control = ChatControl(control_layer(), upstream, sink=sink, check_tools=False)
    return Agent(control, gateway("bank", sink=sink))


def tool_messages(upstream: ToolUsingUpstream) -> list[str]:
    last = upstream.requests[-1]["messages"]
    return [m["content"] for m in last if m["role"] == "tool"]


def test_model_gets_the_gateway_tools() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "CLT-1"})

    # when
    asyncio.run(agent(upstream).complete(QUESTION, "trace"))

    # then
    names = {t["function"]["name"] for t in upstream.requests[0]["tools"]}
    assert names == {"bank__get_client", "bank__get_note"}


def test_tool_call_runs_and_model_answers_from_result() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "CLT-1"})
    calls.clear()

    # when
    response = asyncio.run(agent(upstream).complete(QUESTION, "trace"))

    # then
    assert calls == [{"client_id": "CLT-1"}]
    [result] = tool_messages(upstream)
    assert result.startswith(OPEN)
    reply = response["choices"][0]["message"]["content"]
    assert "Golden Socks Family Office" in reply


def test_result_is_wrapped_once() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "CLT-1"})

    # when
    asyncio.run(agent(upstream).complete(QUESTION, "trace"))

    # then
    [result] = tool_messages(upstream)
    assert result.count(OPEN) == 1


def test_injected_result_never_reaches_model() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_note", {"note_id": "1"})

    # when
    asyncio.run(agent(upstream).complete(QUESTION, "trace"))

    # then
    [result] = tool_messages(upstream)
    assert INJECTION not in result
    assert "withheld" in result


def test_injected_call_blocked_before_server() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": INJECTION})
    calls.clear()

    # when
    asyncio.run(agent(upstream).complete(QUESTION, "trace"))

    # then
    assert calls == []
    [result] = tool_messages(upstream)
    assert "blocked" in result


def test_tool_calls_go_into_the_chat_trace() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "CLT-1"})
    sink = ListSink()

    # when
    asyncio.run(agent(upstream, sink).complete(QUESTION, "trace"))

    # then
    assert {event["trace_id"] for event in sink.events} == {"trace"}
    # The chat's request comes first, so the dashboard shows its prompt.
    requests = [e.get("tool") for e in sink.events if e["event"] == "request"]
    assert requests == [None, "get_client", None]


def test_last_step_answers_without_tools() -> None:
    # given
    upstream = ToolUsingUpstream(
        "bank__get_client", {"client_id": "CLT-1"}, always=True
    )

    # when
    asyncio.run(agent(upstream).complete(QUESTION, "trace"))

    # then
    assert len(upstream.requests) == MAX_STEPS
    assert upstream.requests[-1]["tool_choice"] == "none"
    assert "tool_choice" not in upstream.requests[-2]


def test_failing_server_ends_the_call_not_the_chat() -> None:
    # given
    @asynccontextmanager
    async def broken(server: UpstreamServer) -> AsyncIterator[Client]:
        raise ConnectionError("connection refused")
        yield

    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "CLT-1"})
    subject = agent(upstream)
    subject.gateway.connect = broken

    # when
    asyncio.run(subject.complete(QUESTION, "trace"))

    # then
    assert tool_messages(upstream) == [FAILED.format(tool="bank__get_client")]


def test_stream_runs_tools_then_streams_answer() -> None:
    # given
    upstream = ToolUsingUpstream("bank__get_client", {"client_id": "CLT-1"})

    async def run() -> list[dict[str, Any]]:
        return [part async for part in agent(upstream).stream(QUESTION, "trace")]

    # when
    parts = asyncio.run(run())

    # then
    deltas = [part["choices"][0]["delta"] for part in parts]
    assert not any("tool_calls" in delta for delta in deltas)
    text = "".join(delta.get("content") or "" for delta in deltas)
    assert "Golden Socks Family Office" in text
    assert parts[-1]["choices"][0]["finish_reason"] == "stop"
