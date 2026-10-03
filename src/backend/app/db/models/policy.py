import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Policy(Base):
    """The policy saved for a role, a job title in users, or for everyone
    else. A role with no row follows the default policy."""

    __tablename__ = "policies"

    role: Mapped[str] = mapped_column(String(255), primary_key=True)
    # PolicySettings as JSON, so a new setting needs no migration.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # The user who saved it last.
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="policies_updated_by_id_fkey")
    )
