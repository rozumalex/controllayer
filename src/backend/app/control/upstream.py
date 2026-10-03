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


class OpenAIUpstream:
    """OpenAI's chat completions API, always with one model."""

    def __init__(self, api_key: str, model: str, url: str = OPENAI_URL) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        request = {**request, "model": self.model}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(self.url, json=request, headers=headers)
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
            **request,
            "model": self.model,
            "stream": True,
            # Without it, a stream doesn't say how many tokens it used.
            "stream_options": {"include_usage": True},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with (
                httpx.AsyncClient(timeout=120) as client,
                client.stream(
                    "POST", self.url, json=request, headers=headers
                ) as response,
            ):
                if response.is_error:
                    await response.aread()
                    raise UpstreamError(response.status_code, error_body(response))
                # Server-sent events: one "data: {chunk}" line per chunk, and
                # "data: [DONE]" at the end.
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
                        body = {"error": {"message": message}}
                        raise UpstreamError(502, body) from error
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
