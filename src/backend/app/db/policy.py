import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import BigInteger, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.control.envelope import Direction
from app.control.guards.lockout import ATTACKS, INJECTIONS
from app.control.guards.loop import Call, LoopGuard
from app.control.guards.spoiled_tool import Tool
from app.core.config import settings
from app.core.schema.policy import (
    Budget,
    Clearance,
    Lockout,
    PolicySettings,
    ToolAction,
)
from app.db.models import BankDataCatalog, ControlEvent, Policy

# The key of the default policy. No job title is a bare asterisk.
DEFAULT_ROLE = "*"


def builtin_policy() -> PolicySettings:
    """The default policy until someone saves one: the environment's
    threshold and chat models, internal data, every tool, no budget."""
    return PolicySettings(
        injection_threshold=settings.control_injection_threshold,
        clearance=Clearance.INTERNAL,
        above_clearance=ToolAction.REDACT,
        allowed_models=settings.chat_models,
        budget=Budget(),
        lockout=Lockout(
            blocks=settings.control_lockout_blocks,
            minutes=max(1, settings.control_lockout_window_seconds // 60),
        ),
        default_tool_action=ToolAction.ALLOW,
    )


async def saved_policy(
    session: AsyncSession, org_id: uuid.UUID | None, role: str | None
) -> Policy | None:
    """The policy the organization saved for the role, if any."""
    if org_id is None or role is None:
        return None
    return await session.get(Policy, (org_id, role))


async def default_policy(
    session: AsyncSession, org_id: uuid.UUID | None
) -> PolicySettings:
    saved = await saved_policy(session, org_id, DEFAULT_ROLE)
    return PolicySettings(**saved.settings) if saved else builtin_policy()


async def role_policy(
    session: AsyncSession, org_id: uuid.UUID | None, role: str | None
) -> PolicySettings:
    """The policy an employee of the organization with this job title works
    under."""
    saved = await saved_policy(session, org_id, role)
    if saved:
        return PolicySettings(**saved.settings)
    return await default_policy(session, org_id)


async def data_catalog(session: AsyncSession) -> dict[tuple[str, str], Clearance]:
    """The sensitivity of every field of the bank's data, by table and field."""
    rows = await session.scalars(select(BankDataCatalog))
    return {(r.table_name, r.field_name): Clearance(r.sensitivity) for r in rows}


def price(model: str) -> tuple[Decimal, Decimal]:
    """US dollars per million prompt and completion tokens. OpenAI answers
    with a dated name, such as gpt-4.1-mini-2025-04-14, so the longest known
    name it starts with sets the price. An unknown model costs nothing."""
    known = [name for name in settings.models if model.startswith(name)]
    if not known:
        return Decimal(0), Decimal(0)
    return settings.models[max(known, key=len)].price


def cost(model: str, prompt: int, completion: int) -> Decimal:
    """What the model's tokens cost, in US dollars."""
    prompt_price, completion_price = price(model)
    return (prompt * prompt_price + completion * completion_price) / 1_000_000


async def spent_since(
    session: AsyncSession, user_id: uuid.UUID, start: datetime
) -> Decimal:
    """What the user's chats cost since start, in US dollars, from the model
    responses in the control layer's events."""
    usage = ControlEvent.data["usage"]
    model = func.coalesce(ControlEvent.data["model"].astext, "")
    totals = await session.execute(
        select(
            model,
            func.sum(usage["prompt_tokens"].astext.cast(BigInteger)),
            func.sum(usage["completion_tokens"].astext.cast(BigInteger)),
        )
        .where(
            ControlEvent.user_id == user_id,
            ControlEvent.event == "upstream_response",
            ControlEvent.created_at >= start,
        )
        .group_by(model)
    )
    return sum(
        (
            cost(name, prompt or 0, completion or 0)
            for name, prompt, completion in totals
        ),
        Decimal(0),
    )


async def spent_this_week(session: AsyncSession, user_id: uuid.UUID) -> Decimal:
    """What the user spent this week, from Monday (UTC)."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return await spent_since(session, user_id, today - timedelta(days=today.weekday()))


async def recent_questions(session: AsyncSession, user_id: uuid.UUID) -> int:
    """The questions the user asked in the last minute, blocked ones too. A
    question is one trace: the agent may call the model a few times for it."""
    start = datetime.now(UTC) - timedelta(minutes=1)
    count = await session.scalar(
        select(func.count(func.distinct(ControlEvent.trace_id))).where(
            ControlEvent.user_id == user_id,
            ControlEvent.event == "request",
            ControlEvent.created_at >= start,
        )
    )
    return count or 0


async def recent_flows(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[set[str], set[str]]:
    """What the data flow guard remembered of the user's tool results within
    its window: the kinds of sensitive data read, and the hashes of the
    identifiers seen."""
    start = datetime.now(UTC) - timedelta(minutes=settings.control_flow_window_minutes)
    memories = await session.scalars(
        select(ControlEvent.data["memory"]).where(
            ControlEvent.user_id == user_id,
            ControlEvent.event == "verdict",
            ControlEvent.data["guard"].astext == "data_flow",
            ControlEvent.data.has_key("memory"),
            ControlEvent.created_at >= start,
        )
    )
    labels: set[str] = set()
    seen: set[str] = set()
    for memory in memories:
        labels.update(memory.get("labels", []))
        seen.update(memory.get("seen", []))
    return labels, seen


async def recent_tool_calls(
    session: AsyncSession, user_id: uuid.UUID, seconds: int
) -> list[Call]:
    """The tool calls the user made in the last seconds, blocked ones too, as
    the loop guard's verdicts saved them: server, tool and arguments hash."""
    start = datetime.now(UTC) - timedelta(seconds=seconds)
    data = ControlEvent.data
    rows = await session.execute(
        select(
            data["server"].astext, data["tool"].astext, data["payload_sha256"].astext
        ).where(
            ControlEvent.user_id == user_id,
            ControlEvent.event == "verdict",
            data["guard"].astext == LoopGuard.name,
            ControlEvent.created_at >= start,
        )
    )
    return [(server, tool, sha) for server, tool, sha in rows]


async def recent_blocks(session: AsyncSession, user_id: uuid.UUID, seconds: int) -> int:
    """How many of the user's attacks the layer blocked in the last seconds,
    since an admin last unlocked them: blocks by an attack guard on what
    they sent or the answer they drew out, not on a tool's result."""
    start = datetime.now(UTC) - timedelta(seconds=seconds)
    # An admin's unlock wipes the slate.
    unlocked = await session.scalar(
        select(func.max(ControlEvent.created_at)).where(
            ControlEvent.user_id == user_id, ControlEvent.event == "unlock"
        )
    )
    if unlocked and unlocked > start:
        start = unlocked
    data = ControlEvent.data
    return (
        await session.scalar(
            select(func.count(func.distinct(ControlEvent.trace_id))).where(
                ControlEvent.user_id == user_id,
                ControlEvent.event == "decision",
                ControlEvent.action == "block",
                data["direction"].astext != Direction.OUTBOUND,
                data["guard"].astext.in_(ATTACKS),
                ControlEvent.created_at >= start,
            )
        )
        or 0
    )


async def poisoned_tools(
    session: AsyncSession, org_id: uuid.UUID | None, seconds: int
) -> dict[Tool, int]:
    """How many different results each of the organization's tools sent in
    the last seconds that an injection guard blocked."""
    start = datetime.now(UTC) - timedelta(seconds=seconds)
    data = ControlEvent.data
    server, tool = data["server"].astext, data["tool"].astext
    rows = await session.execute(
        select(server, tool, func.count(func.distinct(data["payload_sha256"].astext)))
        .where(
            ControlEvent.org_id == org_id,
            ControlEvent.event == "decision",
            ControlEvent.action == "block",
            data["direction"].astext == Direction.OUTBOUND,
            data["guard"].astext.in_(INJECTIONS),
            ControlEvent.created_at >= start,
        )
        .group_by(server, tool)
    )
    return {(server, tool): count for server, tool, count in rows}
