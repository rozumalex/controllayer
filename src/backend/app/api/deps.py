import uuid
from collections.abc import Iterable, Sequence
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
from app.control.guards.lockout import LockoutGuard
from app.control.guards.loop import Call, LoopGuard
from app.control.guards.policy import (
    BudgetGuard,
    Catalog,
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
from app.control.pipeline import Mode
from app.control.upstream import ChatUpstream, MockUpstream, OpenAIUpstream
from app.core.assistant import ASSISTANT_MODEL, SYSTEM_PROMPT
from app.core.config import settings
from app.core.schema.chat import ChatCompletionRequest
from app.core.schema.policy import PolicySettings
from app.db.auth import token_user
from app.db.event_sink import DatabaseEventSink
from app.db.models import McpServer, User
from app.db.policy import (
    data_catalog,
    recent_blocks,
    recent_flows,
    recent_questions,
    recent_tool_calls,
    role_policy,
    spent_this_week,
)
from app.db.session import SessionLocal


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


Authorization = Annotated[
    str | None,
    Header(
        description=(
            "`Bearer <token>`, with the token from `/api/auth/sign-in`. OpenAI "
            "clients send it as their API key."
        )
    ),
]


async def current_user(authorization: Authorization = None) -> User:
    """The user the session token signs in, or 401."""
    token = bearer_token(authorization)
    async with SessionLocal() as session:
        user = await token_user(session, token) if token else None
    if user is None:
        raise HTTPException(401, "Sign in first")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def current_org_id(user: CurrentUser) -> uuid.UUID:
    """The signed-in user's organization, whose data alone they see, or 403
    if they belong to none."""
    if user.org_id is None:
        raise HTTPException(403, "The user belongs to no organization")
    return user.org_id


OrgId = Annotated[uuid.UUID, Depends(current_org_id)]

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


async def first_employee(org_id: uuid.UUID | None, role: str) -> User | None:
    """An active employee of the organization with the job title, the same one
    each time. By ID, not by name, so the roles' employees don't all start
    with A."""
    async with SessionLocal() as session:
        return await session.scalar(
            select(User)
            .where(User.org_id == org_id, User.title == role, User.active)
            .order_by(User.id)
            .limit(1)
        )


async def acting_user(
    user: CurrentUser,
    x_simulate_role: Annotated[
        str | None,
        Header(
            description="For the attack simulator: a privileged user acts as "
            "the first employee with this job title."
        ),
    ] = None,
) -> User:
    """The user the request acts as: the signed-in user, or in the attack
    simulator, the employee whose account the attacker took over."""
    if not x_simulate_role or user.clearance_level != PRIVILEGED:
        return user
    return await first_employee(user.org_id, x_simulate_role) or user


ActingUser = Annotated[User, Depends(acting_user)]


def simulated_mode(
    user: CurrentUser,
    x_simulate_security: Annotated[
        str | None,
        Header(
            description="For the attack simulator: `off` makes the guards "
            "only log, for a privileged user."
        ),
    ] = None,
) -> Mode | None:
    """The OFF mode when a privileged user turns security off in the attack
    simulator; otherwise the configured mode."""
    if x_simulate_security == "off" and user.clearance_level == PRIVILEGED:
        return Mode.OFF
    return None


SimulatedMode = Annotated[Mode | None, Depends(simulated_mode)]


async def user_policy(user: ActingUser) -> PolicySettings:
    """The policy of the user's role, read on every request, so a policy
    saved in the admin pages applies to the next one."""
    async with SessionLocal() as session:
        return await role_policy(session, user.org_id, user.title)


UserPolicy = Annotated[PolicySettings, Depends(user_policy)]


def lockout(policy: PolicySettings, blocked: int) -> LockoutGuard:
    """Locks the user out after too many blocked requests, as their role's
    policy says; blocked is how many of theirs were blocked in the window."""
    return LockoutGuard(policy.lockout.blocks, policy.lockout.seconds, blocked)


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
    mode: Mode | None = None,
) -> ControlLayer:
    # Built on every request, so a setting changed at runtime applies to the
    # next one. The user's policy sets the injection threshold.
    threshold = (
        policy.injection_threshold if policy else settings.control_injection_threshold
    )
    return build_layer(
        mode or settings.control_mode,
        threshold,
        EventAuditSink(sink or event_sink()),
        semantic_guard(threshold),
        inbound,
        outbound,
        response,
        SignatureGuard(signature_feed(), settings.control_signature_threshold),
    )


async def chat_control(
    user: ActingUser,
    policy: UserPolicy,
    request: ChatCompletionRequest,
    mode: SimulatedMode,
) -> ChatControl:
    """The control layer for one chat completion. For the bank assistant, the
    server runs the conversation and its tools, through the MCP gateway. For
    a model from the pool, the client runs them, so the layer checks the
    tool calls and results in the messages itself."""
    sink = UserEventSink(event_sink(), user.id, user.org_id)
    assistant = request.model == ASSISTANT_MODEL
    model = chat_model(policy) if assistant else request.model
    async with SessionLocal() as session:
        weekly = await spent_this_week(session, user.id)
        recent = await recent_questions(session, user.id)
        blocked = await recent_blocks(session, user.id, policy.lockout.seconds)
    guards = [
        lockout(policy, blocked),
        RateLimitGuard(settings.control_rate_limit_per_minute, recent),
        ModelGuard(model, policy.allowed_models),
        BudgetGuard(policy.budget, weekly),
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
        control_layer(sink, policy, inbound=guards, response=answer, mode=mode),
        chat_upstream(model),
        sink,
        check_tools=not assistant,
    )


async def enabled_mcp_servers(org_id: uuid.UUID | None) -> list[McpServer]:
    """The organization's MCP servers that are turned on."""
    async with SessionLocal() as session:
        servers = await session.scalars(
            select(McpServer).where(McpServer.enabled, McpServer.org_id == org_id)
        )
        return list(servers)


def mcp_connect() -> Connect:
    return connect_http


async def mcp_gateway(
    user: ActingUser, policy: UserPolicy, mode: SimulatedMode = None
) -> McpGateway:
    async with SessionLocal() as session:
        catalog = await data_catalog(session)
        labels, seen = await recent_flows(session, user.id)
        recent = await recent_tool_calls(
            session, user.id, settings.control_loop_window_seconds
        )
        blocked = await recent_blocks(session, user.id, policy.lockout.seconds)
    sink = UserEventSink(event_sink(), user.id, user.org_id)
    return gateway(
        user, policy, catalog, sink, labels, seen, recent, blocked, mode=mode
    )


def gateway(
    user: User,
    policy: PolicySettings,
    catalog: Catalog,
    sink: EventSink,
    labels: Iterable[str] = (),
    seen: Iterable[str] = (),
    recent: Sequence[Call] = (),
    blocked: int = 0,
    connect: Connect | None = None,
    mode: Mode | None = None,
) -> McpGateway:
    """The gateway for one request, with what the guards remember of the
    user's earlier ones: the data flow guard's labels and hashes, and the
    loop guard's recent calls."""
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
            [lockout(policy, blocked), loop, tool_access(policy), patterns, flow],
            [flow, clearance, patterns],
            mode=mode,
        ),
        connect or mcp_connect(),
        lambda: enabled_mcp_servers(user.org_id),
        sink,
    )


def chat_agent(
    control: Annotated[ChatControl, Depends(chat_control)],
    gateway: Annotated[McpGateway, Depends(mcp_gateway)],
    policy: UserPolicy,
    mode: SimulatedMode,
) -> Agent:
    # With security off, the model gets every tool.
    allows = tool_access(policy).allows if mode is not Mode.OFF else None
    return Agent(control, gateway, allows=allows or (lambda name: True))
