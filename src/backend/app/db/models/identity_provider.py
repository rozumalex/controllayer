import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdentityProvider(Base):
    """An organization's own identity provider, such as Okta or Entra ID.
    Its users sign in through it, and its claims decide their role."""

    __tablename__ = "identity_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # One provider an organization.
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", name="identity_providers_org_id_fkey"),
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    issuer: Mapped[str] = mapped_column(String(2048))
    client_id: Mapped[str] = mapped_column(String(255))
    # Only for providers that won't take PKCE alone. A secret: the API never
    # returns it.
    client_secret: Mapped[str | None] = mapped_column(String(4096))
    scopes: Mapped[str] = mapped_column(
        String(1024), server_default="openid profile email"
    )
    # Email domains that sign in through it, such as ["acme.com"].
    domains: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    # [{"claim": "groups", "value": "sg-ai-compliance", "role": "Compliance
    # Officer", "admin": false}, ...]: the first that matches sets the role.
    role_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    # The role when no rule matches; empty refuses the sign-in.
    default_role: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SsoLogin(Base):
    """A sign-in on its way through a provider: the secrets its callback
    checks. Used once, and only for a few minutes."""

    __tablename__ = "sso_logins"

    # The SHA-256 of the state the browser carries back.
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "identity_providers.id",
            name="sso_logins_provider_id_fkey",
            ondelete="CASCADE",
        )
    )
    nonce: Mapped[str] = mapped_column(String(128))
    code_verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
