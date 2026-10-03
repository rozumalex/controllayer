from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmailCode(Base):
    """The one-time code last sent to an email for signing in. A new code
    replaces the old one; signing in deletes it."""

    __tablename__ = "email_codes"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    # The SHA-256 of the email and the code, never the code itself.
    code_hash: Mapped[str] = mapped_column(String(64))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Wrong codes tried; past the limit the code is void.
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
