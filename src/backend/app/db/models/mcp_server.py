import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class McpServer(Base):
    """An MCP server behind the control layer. Its tools are served to the
    agents of its organization through the gateway."""

    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="mcp_servers_org_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # Empty only until the seed assigns the rows that predate organizations.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", name="mcp_servers_org_id_fkey"), index=True
    )
    # The prefix of its tools in the gateway: <name>__<tool>. Unique within
    # the organization.
    name: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(2048))
    # The Authorization header sent to the server, such as "Bearer <token>".
    # A secret: the API never returns it.
    auth_header: Mapped[str | None] = mapped_column(String(4096))
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    # The SHA-256 of each tool's definition, by tool name, as an admin last
    # approved it, or as the gateway first saw it. A tool whose definition
    # differs is hidden until an admin approves it again (a rug pull).
    tool_pins: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # The users who added it and who last turned it on or off.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="mcp_servers_created_by_id_fkey")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="mcp_servers_updated_by_id_fkey")
    )
