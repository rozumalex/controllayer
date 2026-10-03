import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.control.layer import GUARDS, GuardSettings, default_settings
from app.core.config import settings
from app.core.schema.controls import GuardSettingsModel
from app.db.models import GuardSetting

logger = logging.getLogger("app.control.settings")


def defaults() -> dict[str, GuardSettings]:
    """Every guard's settings before an operator changes them, from the
    environment."""
    return {
        spec.name: default_settings(
            spec, settings.control_mode, settings.control_injection_threshold
        )
        for spec in GUARDS
    }


async def saved(session: AsyncSession) -> dict[str, GuardSettings]:
    """The settings operators saved, by guard. A row that no longer fits the
    settings is skipped, so its guard runs with the defaults."""
    found: dict[str, GuardSettings] = {}
    for row in await session.scalars(select(GuardSetting)):
        try:
            found[row.guard] = GuardSettingsModel.model_validate(
                row.settings
            ).settings()
        except ValidationError:
            logger.warning("ignoring invalid settings of guard %s", row.guard)
    return found


async def load_controls(session: AsyncSession) -> dict[str, GuardSettings]:
    return defaults() | await saved(session)
