import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, false, func
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
    # A demo sandbox: a copy of the demo organization for one visitor.
    sandbox: Mapped[bool] = mapped_column(default=False, server_default=false())
    # The SHA-256 of the key the visitor's browser made, which signs it back in
    # to the same sandbox. Empty on a sandbox no one has claimed yet.
    sandbox_key_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
