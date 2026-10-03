import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import chat_control
from app.control.upstream import UpstreamError
from app.core.schema.openai import ChatCompletionRequest

router = APIRouter(prefix="/v1", tags=["openai"])


@router.post(
    "/chat/completions",
    summary="Create a chat completion through the control layer",
    description=(
        "An OpenAI-compatible endpoint: point an OpenAI client's base URL at "
        "`/api/v1`. It answers with the OpenAI model set on the server. The "
        "control layer checks the prompt and the tool results "
        "before the model sees them, and the tool calls the model returns. "
        "The response has an extra `control_layer` field with every verdict."
    ),
)
async def chat_completions(request: ChatCompletionRequest) -> Any:
    trace_id = uuid4().hex
    try:
        response = await chat_control().complete(request.model_dump(), trace_id)
    except UpstreamError as error:
        return JSONResponse(error.body, status_code=error.status_code)
    headers = {"X-Control-Trace-Id": trace_id}
    if request.stream:
        return StreamingResponse(
            sse(response), media_type="text/event-stream", headers=headers
        )
    return JSONResponse(response, headers=headers)


def sse(response: dict[str, Any]) -> Iterator[str]:
    """The finished completion as a stream: one chunk per choice. The layer
    must see the whole answer before it lets any of it through."""
    for choice in response["choices"]:
        message = choice["message"]
        delta = {"role": "assistant", "content": message.get("content")}
        if message.get("tool_calls"):
            delta["tool_calls"] = [
                {**call, "index": i} for i, call in enumerate(message["tool_calls"])
            ]
        chunk = {
            "id": response.get("id"),
            "object": "chat.completion.chunk",
            "created": response.get("created"),
            "model": response.get("model"),
            "choices": [
                {
                    "index": choice["index"],
                    "delta": delta,
                    "finish_reason": choice["finish_reason"],
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"
