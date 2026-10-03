"""Sends email through SMTP: Mailpit in development, a provider such as
Resend in production. smtplib blocks, so it runs in a thread."""

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings


class MailError(Exception):
    pass


def _send(message: EmailMessage) -> None:
    host, port = settings.smtp_host, settings.smtp_port
    if settings.smtp_tls == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=10)
    else:
        server = smtplib.SMTP(host, port, timeout=10)
    with server:
        if settings.smtp_tls == "starttls":
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def send_mail(to: str, subject: str, text: str) -> None:
    if not settings.smtp_host:
        raise MailError("no SMTP_HOST")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    try:
        await asyncio.to_thread(_send, message)
    except (OSError, smtplib.SMTPException) as error:
        raise MailError(type(error).__name__) from error
