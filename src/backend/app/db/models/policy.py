import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Policy(Base):
    """The policy an organization saved for a role, a job title in users, or
    for everyone else. A role with no row follows the default policy."""

    # A new table, not policies with a new column: the key changed, and a
    # migration can't change a primary key. The seed fills it again.
    __tablename__ = "role_policies"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", name="role_policies_org_id_fkey"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(255), primary_key=True)
    # PolicySettings as JSON, so a new setting needs no migration.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="role_policies_updated_by_id_fkey")
    )
