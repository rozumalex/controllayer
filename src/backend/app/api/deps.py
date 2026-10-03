from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.control.adapters.openai_chat import ChatControl
from app.control.audit import EventAuditSink, EventSink, FanOutSink, LogEventSink
from app.control.layer import ControlLayer, GuardSettings, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.config import settings
from app.db.controls import defaults, load_controls
from app.db.event_sink import DatabaseEventSink
from app.db.session import get_session


def event_sink() -> EventSink:
    # Every event goes to the logs and to the database, where the dashboard
    # reads it.
    return FanOutSink(LogEventSink(), DatabaseEventSink())


def control_layer(controls: Mapping[str, GuardSettings] | None = None) -> ControlLayer:
    return build_layer(controls or defaults(), EventAuditSink(event_sink()))


async def chat_control(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatControl:
    upstream: ChatUpstream = (
        OpenAIUpstream(settings.openai_api_key, settings.openai_model)
        if settings.openai_api_key
        else MockUpstream()
    )
    # The layer is built on every request from the saved controls, so a
    # change on the dashboard applies to the next one.
    return ChatControl(
        control_layer(await load_controls(session)),
        upstream,
        settings.control_log_payloads,
        event_sink(),
    )
