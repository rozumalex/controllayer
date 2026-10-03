import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class McpServer(Base):
    """An MCP server behind the control layer. Its tools are served to every
    agent through the gateway at /api/mcp."""

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # The prefix of its tools in the gateway: <name>__<tool>.
    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(2048))
    # The Authorization header sent to the server, such as "Bearer <token>".
    # A secret: the API never returns it.
    auth_header: Mapped[str | None] = mapped_column(String(4096))
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
