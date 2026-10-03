import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import User


class DirectoryEvent(Base):
    """One change the IdP's provisioning made to the organization's directory,
    such as a user created, moved to another group or deactivated, for the
    provisioning log on the IdP tab."""

    __tablename__ = "directory_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", name="directory_events_org_id_fkey"),
        index=True,
    )
    # created, updated, joined, left, role, deactivated, reactivated or synced.
    kind: Mapped[str] = mapped_column(String(32))
    # The user it changed; empty for a change to the whole directory.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="directory_events_user_id_fkey", ondelete="CASCADE")
    )
    # Loaded with the event, so the log can name the user.
    user: Mapped[User | None] = relationship(lazy="joined")
    # The group, the new role or the counts, as the kind needs.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
