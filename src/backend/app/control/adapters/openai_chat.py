"""Runs an OpenAI chat completion through the control layer.

What the agent sends is checked before the model sees it: the new user prompt
(inbound) and every tool result (outbound, where indirect injection comes
from). What the model returns is checked before the agent acts on it: every
tool call it asks for (inbound, agent -> tool).
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.control.audit import EventSink, LogEventSink
from app.control.envelope import Action, Direction, Envelope
from app.control.guards.sensitive_data import scrub
from app.control.layer import ControlLayer
from app.control.pipeline import Decision
from app.control.upstream import ChatUpstream, UpstreamError, chunk, completion

logger = logging.getLogger("app.control.chat")

# The messages don't say why: the matched patterns would show an attacker what
# to reword. The reasons are in the logs, under the trace id.
WITHHELD = "[control layer] This tool result was withheld."
BLOCKED_PROMPT = "The request was blocked."
BLOCKED_CALL = "A call to {tool} was blocked."


def text_of(content: Any) -> str:
    """The text of a message, whether its content is a string or a list of
    parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


@dataclass
class Trace:
    trace_id: str
    agent_id: str


class ChatControl:
    def __init__(
        self,
        layer: ControlLayer,
        upstream: ChatUpstream,
        log_payloads: bool,
        sink: EventSink | None = None,
        check_tools: bool = True,
    ) -> None:
        self.layer = layer
        self.upstream = upstream
        self.log_payloads = log_payloads
        self.sink = sink or LogEventSink(logger)
        # Off when the tools run through the MCP gateway, which checks every
        # call and result itself: checking them here too would wrap each
        # result twice and pay for the AI check twice.
        self.check_tools = check_tools
        # The user prompts the layer changed, by their original text.
        self.prompts: dict[str, str] = {}

    async def complete(self, request: dict[str, Any], trace_id: str) -> dict[str, Any]:
        trace = Trace(trace_id, agent_id=request.get("user") or "anonymous")
        model = request.get("model", "")
        await self.log(
            trace,
            "request",
            agent_id=trace.agent_id,
            model=model,
            messages=request["messages"],
        )

        messages, blocked = await self.check_messages(request["messages"], trace)
        if blocked:
            response = completion(model, BLOCKED_PROMPT, "content_filter")
        else:
            upstream_request = {**request, "messages": messages, "stream": False}
            await self.log(trace, "upstream_request", messages=messages)
            start = time.perf_counter()
            try:
                response = await self.upstream.complete(upstream_request)
            except UpstreamError as error:
                await self.upstream_failed(trace, error)
                raise
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            await self.log(
                trace,
                "upstream_response",
                latency_ms=latency_ms,
                # The model that answered, so a budget can price the usage.
                model=response.get("model") or model,
                usage=response.get("usage"),
                body=response,
            )
            response = await self.check_response(response, trace)

        finish_reason = response["choices"][0]["finish_reason"]
        await self.log(trace, "response", finish_reason=finish_reason, body=response)
        return response

    async def stream(
        self, request: dict[str, Any], trace_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Like complete, but yields chat.completion.chunk dicts as the model
        writes. Text goes out as it comes. Tool calls are held back to the
        end, because they are checked whole, before the agent can act on
        them."""
        trace = Trace(trace_id, agent_id=request.get("user") or "anonymous")
        model = request.get("model", "")
        id = f"chatcmpl-{uuid4().hex}"
        await self.log(
            trace,
            "request",
            agent_id=trace.agent_id,
            model=model,
            messages=request["messages"],
        )

        messages, blocked = await self.check_messages(request["messages"], trace)
        if blocked:
            await self.log(
                trace, "response", finish_reason="content_filter", body=BLOCKED_PROMPT
            )
            yield chunk(id, model, {"content": BLOCKED_PROMPT}, "content_filter")
            return

        upstream_request = {**request, "messages": messages, "stream": True}
        await self.log(trace, "upstream_request", messages=messages)
        start = time.perf_counter()
        content: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        usage = None
        served = model
        try:
            async for part in self.upstream.stream(upstream_request):
                usage = part.get("usage") or usage
                served = part.get("model") or served
                for choice in part.get("choices", [])[:1]:
                    delta = choice.get("delta") or {}
                    for call in delta.get("tool_calls") or []:
                        add_call_delta(calls, call)
                    finish_reason = choice.get("finish_reason") or finish_reason
                    if delta.get("content"):
                        content.append(delta["content"])
                        yield chunk(id, model, {"content": delta["content"]})
        except UpstreamError as error:
            await self.upstream_failed(trace, error)
            raise
        latency_ms = round((time.perf_counter() - start) * 1000, 3)

        message: dict[str, Any] = {"role": "assistant", "content": "".join(content)}
        if calls:
            message["tool_calls"] = [calls[index] for index in sorted(calls)]
        response = completion(model, "", finish_reason)
        response["choices"][0]["message"] = message
        response["usage"] = usage
        await self.log(
            trace,
            "upstream_response",
            latency_ms=latency_ms,
            model=served,
            usage=usage,
            body=response,
        )
        response = await self.check_response(response, trace)
        choice = response["choices"][0]
        await self.log(
            trace, "response", finish_reason=choice["finish_reason"], body=response
        )

        if choice["finish_reason"] == "content_filter":
            delta = {"content": choice["message"]["content"]}
        elif calls:
            delta = {
                "tool_calls": [
                    {"index": index, **call}
                    for index, call in enumerate(message["tool_calls"])
                ]
            }
        else:
            delta = {}
        yield chunk(id, model, delta, choice["finish_reason"])

    async def check_messages(
        self, messages: list[dict[str, Any]], trace: Trace
    ) -> tuple[list[dict[str, Any]], bool]:
        """Returns the messages to send to the model, and whether to block."""
        # Clients resend the whole history every turn. Only the prompts after
        # the last answer are new; older ones were checked on their own turn.
        new_from = max(
            (i + 1 for i, m in enumerate(messages) if m.get("role") == "assistant"),
            default=0,
        )
        tool_names: dict[str, str] = {}
        checked = []
        for index, message in enumerate(messages):
            for call in message.get("tool_calls") or []:
                tool_names[call.get("id")] = call.get("function", {}).get("name")
            role = message.get("role")
            text = text_of(message.get("content"))
            if role == "user" and index >= new_from:
                decision = await self.inspect(
                    Direction.INBOUND, "llm", "user_prompt", {"content": text}, trace
                )
                if decision.action is Action.BLOCK:
                    return checked, True
                if decision.action is Action.MODIFY:
                    content = decision.envelope.payload["content"]
                    self.prompts[text] = content
                    message = {**message, "content": content}
            elif role == "user" and text in self.prompts:
                # A prompt the layer changed on an earlier step, such as one
                # with PII taken out, goes to the model changed every time.
                message = {**message, "content": self.prompts[text]}
            elif role == "tool" and self.check_tools:
                # Every tool result is checked, so the model never sees one
                # raw, even from an earlier turn.
                tool = tool_names.get(message.get("tool_call_id"), "unknown")
                payload = {"content": text_of(message.get("content"))}
                decision = await self.inspect(
                    Direction.OUTBOUND, "tool", tool, payload, trace
                )
                if decision.action is Action.BLOCK:
                    message = {**message, "content": WITHHELD}
                elif decision.action is Action.MODIFY:
                    content = decision.envelope.payload["content"]
                    message = {**message, "content": content}
            checked.append(message)
        return checked, False

    async def check_response(
        self, response: dict[str, Any], trace: Trace
    ) -> dict[str, Any]:
        if not self.check_tools:
            return response
        for choice in response.get("choices", []):
            message = choice.get("message") or {}
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                tool = function.get("name", "unknown")
                decision = await self.inspect(
                    Direction.INBOUND, "tool", tool, arguments(function), trace
                )
                if decision.action is Action.BLOCK:
                    content = BLOCKED_CALL.format(tool=tool)
                    choice["message"] = {"role": "assistant", "content": content}
                    choice["finish_reason"] = "content_filter"
                    break
        return response

    async def inspect(
        self,
        direction: Direction,
        server: str,
        tool: str,
        payload: dict[str, Any],
        trace: Trace,
    ) -> Decision:
        envelope = Envelope(
            direction=direction,
            agent_id=trace.agent_id,
            server=server,
            tool=tool,
            payload=payload,
            trace_id=trace.trace_id,
        )
        decision = await self.layer.inspect(envelope)
        # What the layer did, next to the verdicts of its guards. In monitor
        # mode a guard may say block while the decision is still allow.
        await self.log(
            trace,
            "decision",
            direction=direction,
            server=server,
            tool=tool,
            action=decision.action,
        )
        return decision

    async def upstream_failed(self, trace: Trace, error: UpstreamError) -> None:
        await self.log(
            trace, "upstream_error", status_code=error.status_code, body=error.body
        )

    async def log(self, trace: Trace, stage: str, **data: Any) -> None:
        payloads = ("messages", "body")
        if not self.log_payloads:
            data = {k: v for k, v in data.items() if k not in payloads}
        # PII and secrets never reach the logs, even with the payloads.
        data = {k: scrub(v) if k in payloads else v for k, v in data.items()}
        await self.sink.write({"event": stage, "trace_id": trace.trace_id, **data})


def add_call_delta(calls: dict[int, dict[str, Any]], delta: dict[str, Any]) -> None:
    """Adds one streamed piece of a tool call to the calls so far. The model
    sends the id and name first, then the arguments in pieces."""
    call = calls.setdefault(
        delta.get("index", 0),
        {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
    )
    if delta.get("id"):
        call["id"] = delta["id"]
    function = delta.get("function") or {}
    call["function"]["name"] += function.get("name") or ""
    call["function"]["arguments"] += function.get("arguments") or ""


def arguments(function: dict[str, Any]) -> dict[str, Any]:
    """The tool call arguments as a dict. The model sends them as a JSON
    string, which may be broken."""
    raw = function.get("arguments") or "{}"
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {"arguments": raw}
    return parsed if isinstance(parsed, dict) else {"arguments": parsed}
