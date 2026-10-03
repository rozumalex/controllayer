import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.schema.policy import Budget, Clearance, PolicySettings, ToolAction
from app.db.models import BankDataCatalog, ControlEvent, Policy

# The key of the default policy. No job title is a bare asterisk.
DEFAULT_ROLE = "*"


def builtin_policy() -> PolicySettings:
    """The default policy until someone saves one: the environment's
    threshold and model, internal data, every tool, no budget."""
    return PolicySettings(
        injection_threshold=settings.control_injection_threshold,
        clearance=Clearance.INTERNAL,
        above_clearance=ToolAction.REDACT,
        allowed_models=[settings.openai_model],
        budget=Budget(),
        default_tool_action=ToolAction.ALLOW,
    )


async def default_policy(session: AsyncSession) -> PolicySettings:
    saved = await session.get(Policy, DEFAULT_ROLE)
    return PolicySettings(**saved.settings) if saved else builtin_policy()


async def role_policy(session: AsyncSession, role: str | None) -> PolicySettings:
    """The policy an employee with this job title works under."""
    saved = await session.get(Policy, role) if role else None
    return PolicySettings(**saved.settings) if saved else await default_policy(session)


async def data_catalog(session: AsyncSession) -> dict[tuple[str, str], Clearance]:
    """The sensitivity of every field of the bank's data, by table and field."""
    rows = await session.scalars(select(BankDataCatalog))
    return {(r.table_name, r.field_name): Clearance(r.sensitivity) for r in rows}


def price(model: str) -> tuple[Decimal, Decimal]:
    """US dollars per million prompt and completion tokens. OpenAI answers
    with a dated name, such as gpt-4.1-mini-2025-04-14, so the longest known
    name it starts with sets the price. An unknown model costs nothing."""
    known = [name for name in settings.model_prices if model.startswith(name)]
    if not known:
        return Decimal(0), Decimal(0)
    return settings.model_prices[max(known, key=len)]


async def monthly_usage(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[int, Decimal]:
    """The tokens the user's chats used this calendar month (UTC), and what
    they cost, from the model responses in the control layer's events."""
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
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
    tokens, usd = 0, Decimal(0)
    for name, prompt, completion in totals:
        prompt, completion = prompt or 0, completion or 0
        prompt_price, completion_price = price(name)
        tokens += prompt + completion
        usd += (prompt * prompt_price + completion * completion_price) / 1_000_000
    return tokens, usd
