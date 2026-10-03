import logging
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import chat_control
from app.control.adapters.openai_chat import ChatControl
from app.control.upstream import UpstreamError
from app.core.schema.chat import ChatRequest, ChatResponse

logger = logging.getLogger("app.control.chat")

router = APIRouter(tags=["chat"])

UPSTREAM_FAILED = {"detail": "The model is unavailable. Try again later."}


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the model through the control layer",
    description=(
        "The control layer checks the message before the model sees it, and "
        "the tool calls the model returns. Its verdicts go to the logs under "
        "the response's `trace_id`, not to the caller."
    ),
)
async def chat(
    request: ChatRequest, control: Annotated[ChatControl, Depends(chat_control)]
) -> Any:
    trace_id = uuid4().hex
    completion = {"messages": [{"role": "user", "content": request.message}]}
    try:
        response = await control.complete(completion, trace_id)
    except UpstreamError as error:
        # The upstream error is about the server's key and the model, not the
        # caller's request, so the caller gets a plain 502.
        logger.warning(
            "upstream failed: trace_id=%s status=%s body=%s",
            trace_id,
            error.status_code,
            error.body,
        )
        return JSONResponse(UPSTREAM_FAILED, status_code=502)
    choice = response["choices"][0]
    return ChatResponse(
        trace_id=trace_id,
        reply=choice["message"].get("content") or "",
        blocked=choice["finish_reason"] == "content_filter",
    )
