import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The organization of the Golden Socks demo bank, which the seed loads.
DEMO_SLUG = "demo"


class Organization(Base):
    """A company that uses the control layer. Its users, policies, MCP servers
    and events are its own: no other organization sees them."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # A short name for URLs and the seed, such as "demo".
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    # The SHA-256 of the token its IdP's SCIM provisioning signs in with.
    scim_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
