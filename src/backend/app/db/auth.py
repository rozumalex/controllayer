import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AuthToken, EmailCode, User


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
            User.active,
        )
    )


def code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}\0{code}".encode()).hexdigest()


async def new_code(session: AsyncSession, email: str) -> str | None:
    """A new six-digit sign-in code for the email, replacing the last one, or
    None if one was sent too recently."""
    now = datetime.now(UTC)
    last = await session.get(EmailCode, email)
    resend = timedelta(seconds=settings.email_code_resend_seconds)
    if last is not None and last.sent_at > now - resend:
        return None
    code = f"{secrets.randbelow(10**6):06d}"
    values = {
        "code_hash": code_hash(email, code),
        "sent_at": now,
        "expires_at": now + timedelta(minutes=settings.email_code_minutes),
        "attempts": 0,
    }
    await session.execute(
        insert(EmailCode)
        .values(email=email, **values)
        .on_conflict_do_update(index_elements=[EmailCode.email], set_=values)
    )
    await session.commit()
    return code


async def use_code(session: AsyncSession, email: str, code: str) -> bool:
    """Whether the code is the one sent to the email, unexpired and with
    tries left. A right code is used up; a wrong one counts as a try."""
    sent = await session.get(EmailCode, email)
    if sent is None:
        return False
    usable = (
        sent.expires_at > datetime.now(UTC)
        and sent.attempts < settings.email_code_attempts
    )
    if usable and hmac.compare_digest(sent.code_hash, code_hash(email, code)):
        await session.delete(sent)
        await session.commit()
        return True
    sent.attempts += 1
    await session.commit()
    return False


async def revoke_token(session: AsyncSession, token: str) -> None:
    await session.execute(
        delete(AuthToken).where(AuthToken.token_hash == token_hash(token))
    )
    await session.commit()
