import uuid
from collections.abc import Sequence
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
from app.control.guard import Guard
from app.control.guards.policy import (
    BudgetGuard,
    ClearanceGuard,
    ModelGuard,
    ToolAccessGuard,
)
from app.control.guards.semantic_injection import (
    OpenAIInjectionClassifier,
    SemanticInjectionGuard,
)
from app.control.layer import ControlLayer, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.config import settings
from app.core.schema.policy import PolicySettings
from app.db.event_sink import DatabaseEventSink
from app.db.models import McpServer, User
from app.db.policy import data_catalog, monthly_usage, role_policy
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


def event_sink() -> EventSink:
    # Every event goes to the logs and to the database, where the dashboard
    # reads it.
    return FanOutSink(LogEventSink(), DatabaseEventSink())


async def user_policy(user: CurrentUser) -> PolicySettings:
    """The policy of the user's role, read on every request, so a policy
    saved in the admin pages applies to the next one."""
    async with SessionLocal() as session:
        return await role_policy(session, user.title)


UserPolicy = Annotated[PolicySettings, Depends(user_policy)]


def chat_model(policy: PolicySettings) -> str:
    """The environment's model if the policy allows it, otherwise the first
    model it allows. With none allowed, the model guard blocks the chat."""
    allowed = policy.allowed_models
    if settings.openai_model in allowed or not allowed:
        return settings.openai_model
    return allowed[0]


def tool_access(policy: PolicySettings) -> ToolAccessGuard:
    return ToolAccessGuard(policy.tools, policy.default_tool_action)


def semantic_guard(threshold: float) -> SemanticInjectionGuard | None:
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
        threshold=threshold,
        fail_closed=settings.control_semantic_fail_closed,
        model=settings.control_semantic_model,
    )


def control_layer(
    sink: EventSink | None = None,
    policy: PolicySettings | None = None,
    inbound: Sequence[Guard] = (),
    outbound: Sequence[Guard] = (),
) -> ControlLayer:
    # Built on every request, so a setting changed at runtime applies to the
    # next one. The user's policy sets the injection threshold.
    threshold = (
        policy.injection_threshold if policy else settings.control_injection_threshold
    )
    return build_layer(
        settings.control_mode,
        threshold,
        EventAuditSink(sink or event_sink()),
        semantic_guard(threshold),
        inbound,
        outbound,
    )


async def chat_control(user: CurrentUser, policy: UserPolicy) -> ChatControl:
    sink = UserEventSink(event_sink(), user.id)
    model = chat_model(policy)
    async with SessionLocal() as session:
        tokens, usd = await monthly_usage(session, user.id)
    guards = [
        ModelGuard(model, policy.allowed_models),
        BudgetGuard(policy.budget, tokens, usd),
    ]
    upstream: ChatUpstream = (
        OpenAIUpstream(settings.openai_api_key, model)
        if settings.openai_api_key
        else MockUpstream()
    )
    # The tools run through the MCP gateway, which checks every call and
    # result, so the chat leaves them to it.
    return ChatControl(
        control_layer(sink, policy, inbound=guards),
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


async def mcp_gateway(user: CurrentUser, policy: UserPolicy) -> McpGateway:
    sink = UserEventSink(event_sink(), user.id)
    async with SessionLocal() as session:
        catalog = await data_catalog(session)
    clearance = ClearanceGuard(
        catalog,
        policy.clearance,
        policy.above_clearance,
        policy.tools,
        policy.default_tool_action,
    )
    return McpGateway(
        control_layer(sink, policy, [tool_access(policy)], [clearance]),
        mcp_connect(),
        enabled_mcp_servers,
        settings.control_log_payloads,
        sink,
    )


def chat_agent(
    control: Annotated[ChatControl, Depends(chat_control)],
    gateway: Annotated[McpGateway, Depends(mcp_gateway)],
    policy: UserPolicy,
) -> Agent:
    return Agent(control, gateway, allows=tool_access(policy).allows)
