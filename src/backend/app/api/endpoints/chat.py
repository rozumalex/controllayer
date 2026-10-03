import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import CurrentUser, chat_agent
from app.control.agent import Agent
from app.control.guards.sensitive_data import scrub
from app.control.upstream import UpstreamError
from app.core.assistant import conversation
from app.core.schema.chat import ChatRequest, ChatResponse

logger = logging.getLogger("app.control.chat")

router = APIRouter(tags=["chat"])

UPSTREAM_FAILED = {"detail": "The model is unavailable. Try again later."}


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the model through the control layer",
    description=(
        "The control layer checks the message before the model sees it. The "
        "model may use the tools of the MCP servers behind the gateway, which "
        "checks each call and its result. The verdicts go to the logs under "
        "the response's `trace_id`, not to the caller."
    ),
)
async def chat(
    request: ChatRequest,
    agent: Annotated[Agent, Depends(chat_agent)],
    user: CurrentUser,
) -> Any:
    trace_id = uuid4().hex
    try:
        response = await agent.complete(conversation(request.message), trace_id)
    except UpstreamError as error:
        # The upstream error is about the server's key and the model, not the
        # caller's request, so the caller gets a plain 502.
        logger.warning(
            "upstream failed: trace_id=%s user_id=%s status=%s body=%s",
            trace_id,
            user.id,
            error.status_code,
            scrub(error.body),
        )
        return JSONResponse(UPSTREAM_FAILED, status_code=502)
    choice = response["choices"][0]
    return ChatResponse(
        trace_id=trace_id,
        reply=choice["message"].get("content") or "",
        blocked=choice["finish_reason"] == "content_filter",
    )


def event(**data: Any) -> str:
    """One server-sent event with a JSON body."""
    return f"data: {json.dumps(data)}\n\n"


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    summary="Stream the model's answer through the control layer",
    description=(
        "Like `/chat`, but the answer comes as server-sent events while the "
        "model writes it. Each event is `data:` and a JSON object: "
        '`{"type": "delta", "text": ...}` for each piece of the answer, then '
        '`{"type": "done", "blocked": ...}`, or `{"type": "error", "detail": '
        "...}` if the model failed. The trace id is in the `X-Trace-Id` header."
    ),
)
async def chat_stream(
    request: ChatRequest,
    agent: Annotated[Agent, Depends(chat_agent)],
    user: CurrentUser,
) -> StreamingResponse:
    trace_id = uuid4().hex
    messages = conversation(request.message)

    async def events() -> AsyncIterator[str]:
        blocked = False
        try:
            async for chunk in agent.stream(messages, trace_id):
                choice = chunk["choices"][0]
                if text := choice["delta"].get("content"):
                    yield event(type="delta", text=text)
                blocked = blocked or choice["finish_reason"] == "content_filter"
        except UpstreamError as error:
            logger.warning(
                "upstream failed: trace_id=%s user_id=%s status=%s body=%s",
                trace_id,
                user.id,
                error.status_code,
                scrub(error.body),
            )
            yield event(type="error", **UPSTREAM_FAILED)
            return
        yield event(type="done", blocked=blocked)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"X-Trace-Id": trace_id, "Cache-Control": "no-cache"},
    )
