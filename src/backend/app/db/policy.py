from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.schema.policy import Budget, Clearance, PolicySettings, ToolAction
from app.db.models import Policy

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
