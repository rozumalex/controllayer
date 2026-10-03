import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import User


class ControlEvent(Base):
    """One event of the control layer: a request, a guard's verdict, the
    layer's decision, a call to the model, the response or an error. The
    events of one request share its trace id."""

    __tablename__ = "control_events"

    # Increasing, so it orders the events of a trace.
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(32))
    # The signed-in user the request came from; empty for events with none.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="control_events_user_id_fkey"), index=True
    )
    # The user's organization, so its dashboard shows only its own events.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", name="control_events_org_id_fkey"),
        index=True,
    )
    # Loaded with the event, so the dashboard can name the user.
    user: Mapped[User | None] = relationship(lazy="joined")
    # The verdict's or the decision's action; empty for the other events.
    action: Mapped[str | None] = mapped_column(String(16))
    # The whole event, as the logs have it.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
