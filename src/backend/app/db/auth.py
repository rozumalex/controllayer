import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AuthToken, User


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    """A new session token for the user, valid for AUTH_SESSION_DAYS."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=settings.auth_session_days)
    session.add(
        AuthToken(token_hash=token_hash(token), user_id=user_id, expires_at=expires_at)
    )
    await session.commit()
    return token


async def token_user(session: AsyncSession, token: str) -> User | None:
    """The user the token signs in, or None if it is unknown or expired."""
    return await session.scalar(
        select(User)
        .join(AuthToken, AuthToken.user_id == User.id)
        .where(
            AuthToken.token_hash == token_hash(token),
            AuthToken.expires_at > datetime.now(UTC),
        )
    )


async def revoke_token(session: AsyncSession, token: str) -> None:
    await session.execute(
        delete(AuthToken).where(AuthToken.token_hash == token_hash(token))
    )
    await session.commit()
