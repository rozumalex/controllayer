import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from app.control.adapters.mcp_gateway import Connect, McpGateway, connect_http
from app.control.adapters.openai_chat import ChatControl
from app.control.agent import Agent
from app.control.audit import (
    EventAuditSink,
    EventSink,
    FanOutSink,
    LogEventSink,
    UserEventSink,
)
from app.control.guards.semantic_injection import (
    OpenAIInjectionClassifier,
    SemanticInjectionGuard,
)
from app.control.layer import ControlLayer, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.config import settings
from app.db.event_sink import DatabaseEventSink
from app.db.models import McpServer, User
from app.db.session import SessionLocal


async def current_user(
    user_id: Annotated[
        uuid.UUID | None,
        Header(description="The ID of the user picked on the sign-in screen."),
    ] = None,
) -> User:
    """The user the caller picked on the sign-in screen. It is a demo sign-in:
    the header names the user, and nothing proves the caller is them."""
    async with SessionLocal() as session:
        user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Pick a user to sign in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]

# The clearance level that opens the admin pages: the dashboard, the MCP
# servers and the policy.
PRIVILEGED = "PRIVILEGED"


async def privileged_user(user: CurrentUser) -> User:
    """The signed-in user, or 403 if their clearance is not privileged."""
    if user.clearance_level != PRIVILEGED:
        raise HTTPException(403, "Only privileged users can open the admin pages")
    return user


def event_sink() -> EventSink:
    # Every event goes to the logs and to the database, where the dashboard
    # reads it.
    return FanOutSink(LogEventSink(), DatabaseEventSink())


def semantic_guard() -> SemanticInjectionGuard | None:
    # Without a key the demo runs offline, on the heuristic guard alone.
    if not settings.openai_api_key:
        return None
    classifier = OpenAIInjectionClassifier(
        settings.openai_api_key,
        settings.control_semantic_model,
        settings.control_semantic_timeout,
    )
    return SemanticInjectionGuard(
        classifier,
        threshold=settings.control_injection_threshold,
        fail_closed=settings.control_semantic_fail_closed,
        model=settings.control_semantic_model,
    )


def control_layer(sink: EventSink | None = None) -> ControlLayer:
    # Built on every request, so a setting changed at runtime applies to the
    # next one.
    return build_layer(
        settings.control_mode,
        settings.control_injection_threshold,
        EventAuditSink(sink or event_sink()),
        semantic_guard(),
    )


def chat_control(user: CurrentUser) -> ChatControl:
    sink = UserEventSink(event_sink(), user.id)
    upstream: ChatUpstream = (
        OpenAIUpstream(settings.openai_api_key, settings.openai_model)
        if settings.openai_api_key
        else MockUpstream()
    )
    # The tools run through the MCP gateway, which checks every call and
    # result, so the chat leaves them to it.
    return ChatControl(
        control_layer(sink),
        upstream,
        settings.control_log_payloads,
        sink,
        check_tools=False,
    )


async def enabled_mcp_servers() -> list[McpServer]:
    async with SessionLocal() as session:
        servers = await session.scalars(select(McpServer).where(McpServer.enabled))
        return list(servers)


def mcp_connect() -> Connect:
    return connect_http


def mcp_gateway(user: CurrentUser) -> McpGateway:
    sink = UserEventSink(event_sink(), user.id)
    return McpGateway(
        control_layer(sink),
        mcp_connect(),
        enabled_mcp_servers,
        settings.control_log_payloads,
        sink,
    )


def chat_agent(
    control: Annotated[ChatControl, Depends(chat_control)],
    gateway: Annotated[McpGateway, Depends(mcp_gateway)],
) -> Agent:
    return Agent(control, gateway)
