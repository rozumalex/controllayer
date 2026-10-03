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
from app.control.guards.data_flow import DataFlowGuard
from app.control.guards.loop import LoopGuard
from app.control.guards.policy import (
    BudgetGuard,
    ClearanceGuard,
    ModelGuard,
    ToolAccessGuard,
)
from app.control.guards.prompt_leak import PromptLeakGuard
from app.control.guards.rate_limit import RateLimitGuard
from app.control.guards.semantic_injection import (
    OpenAIInjectionClassifier,
    SemanticInjectionGuard,
)
from app.control.guards.sensitive_data import SensitiveDataGuard
from app.control.guards.signatures import BUNDLED, Feed, SignatureGuard
from app.control.layer import ControlLayer, build_layer
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.assistant import ASSISTANT_MODEL, SYSTEM_PROMPT
from app.core.config import settings
from app.core.schema.chat import ChatCompletionRequest
from app.core.schema.policy import PolicySettings
from app.db.event_sink import DatabaseEventSink
from app.db.models import McpServer, User
from app.db.policy import (
    data_catalog,
    monthly_usage,
    recent_flows,
    recent_questions,
    recent_tool_calls,
    role_policy,
)
from app.db.session import SessionLocal


def bearer_user_id(authorization: str | None) -> uuid.UUID | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    try:
        return uuid.UUID(token.strip())
    except ValueError:
        return None


async def current_user(
    user_id: Annotated[
        uuid.UUID | None,
        Header(description="The ID of the user picked on the sign-in screen."),
    ] = None,
    authorization: Annotated[
        str | None,
        Header(
            description=(
                "`Bearer <user ID>`, as OpenAI clients send their API key. Used "
                "when there is no User-Id header."
            )
        ),
    ] = None,
) -> User:
    """The user the caller picked on the sign-in screen, from the User-Id
    header, or from the API key of an OpenAI client. It is a demo sign-in:
    the caller names the user, and nothing proves the caller is them."""
    user_id = user_id or bearer_user_id(authorization)
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


async def user_policy(user: CurrentUser) -> PolicySettings:
    """The policy of the user's role, read on every request, so a policy
    saved in the admin pages applies to the next one."""
    async with SessionLocal() as session:
        return await role_policy(session, user.title)


UserPolicy = Annotated[PolicySettings, Depends(user_policy)]


def chat_model(policy: PolicySettings) -> str:
    """The first chat model the policy allows that a provider serves, then
    any other it allows that one serves. With none served, the first it
    allows, which the mock model stands in for. With none allowed, the model
    guard blocks the chat."""
    allowed = policy.allowed_models
    if not allowed:
        return settings.chat_models[0]
    preferred = [m for m in settings.chat_models if m in allowed]
    candidates = preferred + [m for m in allowed if m not in preferred]
    served = [m for m in candidates if settings.endpoint(m)]
    return (served or candidates)[0]


def chat_upstream(model: str) -> ChatUpstream:
    endpoint = settings.endpoint(model)
    if endpoint is None:
        return MockUpstream()
    return OpenAIUpstream(
        endpoint.key,
        model,
        url=f"{endpoint.url}/chat/completions",
        max_tokens=settings.chat_max_tokens,
        max_tokens_field=endpoint.max_tokens_field,
    )


def tool_access(policy: PolicySettings) -> ToolAccessGuard:
    return ToolAccessGuard(policy.tools, policy.default_tool_action)


def sensitive_data(policy: PolicySettings) -> SensitiveDataGuard:
    return SensitiveDataGuard(
        policy.pii,
        policy.clearance,
        policy.above_clearance,
        policy.tools,
        policy.default_tool_action,
    )


def semantic_guard(threshold: float) -> SemanticInjectionGuard | None:
    # With no model served the demo runs offline, on the heuristic guard alone.
    models = settings.control_semantic_models
    served = [(m, e) for m in models if (e := settings.endpoint(m))]
    if not served:
        return None
    model, endpoint = served[0]
    classifier = OpenAIInjectionClassifier(
        endpoint.key,
        model,
        settings.control_semantic_timeout,
        url=f"{endpoint.url}/chat/completions",
        max_tokens_field=endpoint.max_tokens_field,
    )
    return SemanticInjectionGuard(
        classifier,
        threshold=threshold,
        fail_closed=settings.control_semantic_fail_closed,
        model=model,
    )


FEEDS: dict[tuple[str, float], Feed] = {}


def signature_feed() -> Feed:
    """One feed per source for the whole process, so it is read again only
    when it changes, not on every request."""
    source = settings.control_signature_feed or str(BUNDLED)
    key = (source, settings.control_signature_refresh)
    if key not in FEEDS:
        FEEDS[key] = Feed(source, settings.control_signature_refresh)
    return FEEDS[key]


def control_layer(
    sink: EventSink | None = None,
    policy: PolicySettings | None = None,
    inbound: Sequence[Guard] = (),
    outbound: Sequence[Guard] = (),
    response: Sequence[Guard] = (),
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
        response,
        SignatureGuard(signature_feed(), settings.control_signature_threshold),
    )


async def chat_control(
    user: CurrentUser, policy: UserPolicy, request: ChatCompletionRequest
) -> ChatControl:
    """The control layer for one chat completion. For the bank assistant, the
    server runs the conversation and its tools, through the MCP gateway. For
    a model from the pool, the client runs them, so the layer checks the
    tool calls and results in the messages itself."""
    sink = UserEventSink(event_sink(), user.id)
    assistant = request.model == ASSISTANT_MODEL
    model = chat_model(policy) if assistant else request.model
    async with SessionLocal() as session:
        tokens, usd = await monthly_usage(session, user.id)
        recent = await recent_questions(session, user.id)
    guards = [
        RateLimitGuard(settings.control_rate_limit_per_minute, recent),
        ModelGuard(model, policy.allowed_models),
        BudgetGuard(policy.budget, tokens, usd),
        sensitive_data(policy),
    ]
    # The answer is checked too: the model may write PII the policy hides,
    # a secret, or the assistant's instructions.
    answer: list[Guard] = [sensitive_data(policy)]
    if assistant:
        answer.append(PromptLeakGuard(SYSTEM_PROMPT))
    # The assistant's tools run through the MCP gateway, which checks every
    # call and result, so the chat leaves them to it.
    return ChatControl(
        control_layer(sink, policy, inbound=guards, response=answer),
        chat_upstream(model),
        settings.control_log_payloads,
        sink,
        check_tools=not assistant,
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
        labels, seen = await recent_flows(session, user.id)
        recent = await recent_tool_calls(
            session, user.id, settings.control_loop_window_seconds
        )
    # First, so it counts every call, even one another guard blocks.
    loop = LoopGuard(
        settings.control_loop_repeat_limit, settings.control_loop_call_limit, recent
    )
    clearance = ClearanceGuard(
        catalog,
        policy.clearance,
        policy.above_clearance,
        policy.tools,
        policy.default_tool_action,
    )
    patterns = sensitive_data(policy)
    # Sees each result first, as the server sent it, and carries what it saw
    # over from the user's earlier requests.
    flow = DataFlowGuard(labels, seen, clearance)
    return McpGateway(
        control_layer(
            sink,
            policy,
            [loop, tool_access(policy), patterns, flow],
            [flow, clearance, patterns],
        ),
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
