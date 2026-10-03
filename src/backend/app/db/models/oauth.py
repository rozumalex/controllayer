import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OAuthClient(Base):
    """An MCP client, such as Claude, that registered itself to sign users in
    to /api/mcp. Every client is public: it gets no secret, and PKCE guards
    its codes."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Its registration as RFC 7591 returns it, such as its name and its
    # redirect URIs.
    info: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OAuthCode(Base):
    """A code that a user approved for a client, to trade once for a session
    token. The database keeps only its SHA-256."""

    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey(
            "oauth_clients.client_id",
            name="oauth_codes_client_id_fkey",
            ondelete="CASCADE",
        )
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="oauth_codes_user_id_fkey", ondelete="CASCADE")
    )
    # The authorization request: the redirect URI, the PKCE challenge, the
    # scopes and the resource.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
