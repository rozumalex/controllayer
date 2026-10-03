"""The control layer's OpenAI-compatible API. Any OpenAI client reaches the
bank assistant and the model pool through it: it sets the base URL to /api/v1
and the API key to the user's ID."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import CurrentUser, UserPolicy, chat_agent
from app.control.agent import Agent
from app.control.guards.sensitive_data import scrub
from app.control.upstream import UpstreamError
from app.core.assistant import ASSISTANT_MODEL, conversation
from app.core.schema.chat import ChatCompletionRequest, ModelCard, ModelList

logger = logging.getLogger("app.control.chat")

router = APIRouter(prefix="/v1", tags=["chat"])

# OpenAI's error shape, so clients show the message.
UPSTREAM_FAILED = {
    "error": {
        "message": "The model is unavailable. Try again later.",
        "type": "upstream_error",
    }
}


@router.get(
    "/models",
    response_model=ModelList,
    summary="List the models the user may use",
    description=(
        "The bank assistant, then the models from the pool that the user's "
        "policy allows."
    ),
)
async def models(policy: UserPolicy) -> ModelList:
    cards = [ModelCard(id=ASSISTANT_MODEL, owned_by="golden-socks")]
    cards += [ModelCard(id=m, owned_by="controllayer") for m in policy.allowed_models]
    return ModelList(data=cards)


def event(data: dict[str, Any] | str) -> str:
    """One server-sent event, as OpenAI sends them."""
    return f"data: {data if isinstance(data, str) else json.dumps(data)}\n\n"


@router.post(
    "/chat/completions",
    summary="Send a chat completion through the control layer",
    description=(
        "OpenAI's chat completions API. With `golden-socks-assistant`, the "
        "server adds the bank's instructions and runs the tools of the MCP "
        "servers through the gateway. With a model from the pool, the client "
        "sends its own instructions and tools, and the layer checks the tool "
        "calls and results in the messages. Either way, the layer checks the "
        "new prompts before the model sees them and the answer before the "
        "client does. A blocked request or answer comes back as an assistant "
        'message with `finish_reason` `"content_filter"`. The verdicts go to '
        "the logs under the `X-Trace-Id` response header."
    ),
)
async def chat_completions(
    request: ChatCompletionRequest,
    agent: Annotated[Agent, Depends(chat_agent)],
    user: CurrentUser,
) -> Any:
    trace_id = uuid4().hex
    headers = {"X-Trace-Id": trace_id}
    # The user comes from the sign-in, not from the client.
    body = request.model_dump(exclude={"stream", "user"})
    assistant = request.model == ASSISTANT_MODEL

    def run(stream: bool) -> Any:
        if assistant:
            messages = conversation(request.messages)
            if stream:
                return agent.stream(messages, trace_id)
            return agent.complete(messages, trace_id)
        if stream:
            return agent.control.stream(body, trace_id)
        return agent.control.complete(body, trace_id)

    def failed(error: UpstreamError) -> None:
        # The upstream error is about the server's key and the model, not the
        # caller's request, so the caller gets a plain 502.
        logger.warning(
            "upstream failed: trace_id=%s user_id=%s status=%s body=%s",
            trace_id,
            user.id,
            error.status_code,
            scrub(error.body),
        )

    if not request.stream:
        try:
            return JSONResponse(await run(stream=False), headers=headers)
        except UpstreamError as error:
            failed(error)
            return JSONResponse(UPSTREAM_FAILED, status_code=502, headers=headers)

    async def events() -> AsyncIterator[str]:
        try:
            async for chunk in run(stream=True):
                yield event(chunk)
        except UpstreamError as error:
            failed(error)
            yield event(UPSTREAM_FAILED)
        yield event("[DONE]")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={**headers, "Cache-Control": "no-cache"},
    )
