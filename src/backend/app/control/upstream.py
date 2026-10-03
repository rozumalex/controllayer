import time
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
            message = f"upstream model unreachable: {error!r}"
            raise UpstreamError(502, {"error": {"message": message}}) from error
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {"error": {"message": response.text}}
            raise UpstreamError(response.status_code, body)
        return response.json()


class MockUpstream:
    """Echoes the last message back, so the demo shows what the model sees."""

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        messages = request["messages"]
        last = messages[-1]
        content = (
            f"[mock model] I received {len(messages)} messages. "
            f"The last one ({last.get('role')}) was:\n{last.get('content')}"
        )
        return completion("mock", content, "stop")
