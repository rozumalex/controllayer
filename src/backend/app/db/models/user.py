import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    # A random UUIDv4, so the ID reveals nothing about the user. Postgres fills
    # it in for rows inserted without the ORM.
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Golden Socks staff: who they are at the bank. Empty for anyone else.
    division: Mapped[str | None]
    team: Mapped[str | None]
    title: Mapped[str | None]
    office: Mapped[str | None]
    phone: Mapped[str | None]
    # Named, so the migration that adds it can drop it again.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="users_manager_id_fkey")
    )
    # LOW, STANDARD or PRIVILEGED, the levels of the identity profiles.
    clearance_level: Mapped[str | None]
    employment_status: Mapped[str | None]
