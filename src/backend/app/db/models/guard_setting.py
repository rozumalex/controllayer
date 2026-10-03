from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GuardSetting(Base):
    """The settings an operator saved for one guard. A guard with no row runs
    with its defaults."""

    __tablename__ = "guard_settings"

    guard: Mapped[str] = mapped_column(String(64), primary_key=True)
    # GuardSettings as JSON, so a new setting needs no migration.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
