from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import chat_control
from app.control.upstream import UpstreamError
from app.core.schema.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the model through the control layer",
    description=(
        "The control layer checks the message before the model sees it, and "
        "the tool calls the model returns. The response lists every verdict."
    ),
)
async def chat(request: ChatRequest) -> Any:
    trace_id = uuid4().hex
    completion = {"messages": [{"role": "user", "content": request.message}]}
    try:
        response = await chat_control().complete(completion, trace_id)
    except UpstreamError as error:
        return JSONResponse(error.body, status_code=error.status_code)
    choice = response["choices"][0]
    return ChatResponse(
        trace_id=trace_id,
        reply=choice["message"].get("content") or "",
        blocked=choice["finish_reason"] == "content_filter",
        verdicts=response["control_layer"]["verdicts"],
    )
