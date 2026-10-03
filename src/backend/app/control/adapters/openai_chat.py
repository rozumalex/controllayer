"""Runs an OpenAI chat completion through the control layer.

What the agent sends is checked before the model sees it: the new user prompt
(inbound) and every tool result (outbound, where indirect injection comes
from). What the model returns is checked before the agent acts on it: every
tool call it asks for (inbound, agent -> tool).
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.control.envelope import Action, Direction, Envelope
from app.control.layer import ControlLayer
from app.control.pipeline import Decision
from app.control.upstream import ChatUpstream, completion

logger = logging.getLogger("app.control.chat")

WITHHELD = "[control layer] This tool result was withheld: {reason}"
BLOCKED_PROMPT = "[control layer] The request was blocked: {reason}"
BLOCKED_CALL = "[control layer] A call to {tool} was blocked: {reason}"


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


def reason_of(decision: Decision) -> str:
    return "; ".join(v.reason for v in decision.verdicts if v.action is Action.BLOCK)


@dataclass
class Trace:
    trace_id: str
    agent_id: str


class ChatControl:
    def __init__(
        self, layer: ControlLayer, upstream: ChatUpstream, log_payloads: bool
    ) -> None:
        self.layer = layer
        self.upstream = upstream
        self.log_payloads = log_payloads

    async def complete(self, request: dict[str, Any], trace_id: str) -> dict[str, Any]:
        trace = Trace(trace_id, agent_id=request.get("user") or "anonymous")
        model = request.get("model", "")
        self.log(trace, "request", model=model, messages=request["messages"])

        messages, blocked = await self.check_messages(request["messages"], trace)
        if blocked:
            content = BLOCKED_PROMPT.format(reason=blocked)
            response = completion(model, content, "content_filter")
        else:
            upstream_request = {**request, "messages": messages, "stream": False}
            self.log(trace, "upstream_request", messages=messages)
            start = time.perf_counter()
            response = await self.upstream.complete(upstream_request)
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            self.log(trace, "upstream_response", latency_ms=latency_ms, body=response)
            response = await self.check_response(response, trace)

        self.log(trace, "response", body=response)
        return response

    async def check_messages(
        self, messages: list[dict[str, Any]], trace: Trace
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Returns the messages to send to the model, or the reason to block."""
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
            if role == "user" and index >= new_from:
                payload = {"content": text_of(message.get("content"))}
                decision = await self.inspect(
                    Direction.INBOUND, "llm", "user_prompt", payload, trace
                )
                if decision.action is Action.BLOCK:
                    return checked, reason_of(decision)
            elif role == "tool":
                # Every tool result is checked, so the model never sees one
                # raw, even from an earlier turn.
                tool = tool_names.get(message.get("tool_call_id"), "unknown")
                payload = {"content": text_of(message.get("content"))}
                decision = await self.inspect(
                    Direction.OUTBOUND, "tool", tool, payload, trace
                )
                if decision.action is Action.BLOCK:
                    content = WITHHELD.format(reason=reason_of(decision))
                    message = {**message, "content": content}
                elif decision.action is Action.MODIFY:
                    content = decision.envelope.payload["content"]
                    message = {**message, "content": content}
            checked.append(message)
        return checked, None

    async def check_response(
        self, response: dict[str, Any], trace: Trace
    ) -> dict[str, Any]:
        for choice in response.get("choices", []):
            message = choice.get("message") or {}
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                tool = function.get("name", "unknown")
                decision = await self.inspect(
                    Direction.INBOUND, "tool", tool, arguments(function), trace
                )
                if decision.action is Action.BLOCK:
                    content = BLOCKED_CALL.format(tool=tool, reason=reason_of(decision))
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
        return await self.layer.inspect(envelope)

    def log(self, trace: Trace, stage: str, **data: Any) -> None:
        if not self.log_payloads:
            data = {k: v for k, v in data.items() if k not in ("messages", "body")}
        event = {"event": stage, "trace_id": trace.trace_id, **data}
        logger.info(json.dumps(event, default=str))


def arguments(function: dict[str, Any]) -> dict[str, Any]:
    """The tool call arguments as a dict. The model sends them as a JSON
    string, which may be broken."""
    raw = function.get("arguments") or "{}"
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {"arguments": raw}
    return parsed if isinstance(parsed, dict) else {"arguments": parsed}
