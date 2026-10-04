import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import uuid4

import httpx


class UpstreamError(Exception):
    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"upstream returned {status_code}")
        self.status_code = status_code
        self.body = body


class ChatUpstream(Protocol):
    async def complete(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def stream(self, request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """The completion as chat.completion.chunk dicts."""
        ...


def completion(model: str, content: str, finish_reason: str) -> dict[str, Any]:
    """A chat.completion response with one plain assistant message."""
    return {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def chunk(
    id: str, model: str, delta: dict[str, Any], finish_reason: str | None = None
) -> dict[str, Any]:
    """One chat.completion.chunk of a streamed completion."""
    return {
        "id": id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def error_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"error": {"message": response.text}}


def unreachable(error: httpx.HTTPError) -> UpstreamError:
    message = f"upstream model unreachable: {error!r}"
    return UpstreamError(502, {"error": {"message": message}})


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# How often a request the provider turned away for a moment, for a rate
# limit or an outage, is sent again. The waits double from BACKOFF seconds,
# unless the provider says how long to wait.
RETRIES = 3
BACKOFF = 1.0


def busy(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500


def wait(response: httpx.Response, attempt: int) -> float:
    try:
        return float(response.headers["retry-after"])
    except KeyError, ValueError:
        return BACKOFF * 2**attempt


async def chunks(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """The chunks of a streamed completion. Server-sent events: one
    "data: {chunk}" line per chunk, and "data: [DONE]" at the end."""
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except ValueError as error:
            message = f"upstream sent a chunk that is not JSON: {data}"
            raise UpstreamError(502, {"error": {"message": message}}) from error


class OpenAIUpstream:
    """An OpenAI-compatible chat completions API, such as OpenAI's or
    Ollama's, always with one model and at most max_tokens tokens an answer.
    The provider names the field that caps them."""

    def __init__(
        self,
        api_key: str,
        model: str,
        url: str = OPENAI_URL,
        max_tokens: int | None = None,
        max_tokens_field: str = "max_completion_tokens",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url
        self.max_tokens = max_tokens
        self.max_tokens_field = max_tokens_field

    def limit(self, request: dict[str, Any]) -> dict[str, Any]:
        """The request for this model, capped at max_tokens."""
        request = {**request, "model": self.model}
        if self.max_tokens:
            request[self.max_tokens_field] = self.max_tokens
        return request

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        request = self.limit(request)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                for attempt in range(RETRIES + 1):
                    response = await client.post(
                        self.url, json=request, headers=headers
                    )
                    if not busy(response) or attempt == RETRIES:
                        break
                    await asyncio.sleep(wait(response, attempt))
        except httpx.HTTPError as error:
            raise unreachable(error) from error
        if response.is_error:
            raise UpstreamError(response.status_code, error_body(response))
        try:
            return response.json()
        except ValueError as error:
            message = f"upstream returned a body that is not JSON: {response.text}"
            raise UpstreamError(502, {"error": {"message": message}}) from error

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        request = {
            **self.limit(request),
            "stream": True,
            # Without it, a stream doesn't say how many tokens it used.
            "stream_options": {"include_usage": True},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                for attempt in range(RETRIES + 1):
                    async with client.stream(
                        "POST", self.url, json=request, headers=headers
                    ) as response:
                        if busy(response) and attempt < RETRIES:
                            await asyncio.sleep(wait(response, attempt))
                            continue
                        if response.is_error:
                            await response.aread()
                            body = error_body(response)
                            raise UpstreamError(response.status_code, body)
                        async for part in chunks(response):
                            yield part
                        return
        except httpx.HTTPError as error:
            raise unreachable(error) from error


class MockUpstream:
    """Echoes the last message back, so the demo shows what the model sees."""

    def __init__(self, delay: float = 0.02) -> None:
        # The pause between streamed words, so the demo looks like a model.
        self.delay = delay

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        reply = self.reply(request["messages"])
        response = completion("mock", reply, "stop")
        response["usage"] = self.usage(request["messages"], reply)
        return response

    async def stream(self, request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        id = f"chatcmpl-{uuid4().hex}"
        reply = self.reply(request["messages"])
        yield chunk(id, "mock", {"role": "assistant", "content": ""})
        for word in re.findall(r"\s*\S+", reply):
            await asyncio.sleep(self.delay)
            yield chunk(id, "mock", {"content": word})
        yield chunk(id, "mock", {}, "stop")
        # OpenAI sends the usage last, in a chunk with no choices.
        usage = {**chunk(id, "mock", {}), "choices": []}
        yield {**usage, "usage": self.usage(request["messages"], reply)}

    def usage(self, messages: list[dict[str, Any]], reply: str) -> dict[str, int]:
        """A rough token count, about four characters a token, so the demo
        shows usage without a model."""
        prompt = sum(len(str(m.get("content") or "")) for m in messages) // 4 + 1
        answer = len(reply) // 4 + 1
        return {
            "prompt_tokens": prompt,
            "completion_tokens": answer,
            "total_tokens": prompt + answer,
        }

    def reply(self, messages: list[dict[str, Any]]) -> str:
        last = messages[-1]
        return (
            f"I received {len(messages)} messages. "
            f"The last one ({last.get('role')}) was:\n{last.get('content')}"
        )
