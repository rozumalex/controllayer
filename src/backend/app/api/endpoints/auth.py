"""Sign-in: with Google, or with a one-time code sent by email. There are no
passwords and no separate sign-up: a new user's first sign-in creates their
account, and an organization of their own that they administer. Others join
an organization only by invitation."""

import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PRIVILEGED, Authorization, bearer_token
from app.api.endpoints.employees import employee
from app.core.config import settings
from app.core.google import GoogleTokenError
from app.core.google import verify as verify_google
from app.core.mail import MailError, send_mail
from app.core.schema.auth import (
    CodeSent,
    EmailCode,
    EmailSignIn,
    GoogleSignIn,
    SignedIn,
)
from app.db.auth import issue_token, new_code, revoke_token, use_code
from app.db.models import Organization, User
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Mail services where everyone gets an address, so the domain names no
# company: a user from one gets an organization named after them instead.
PUBLIC_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "aol.com",
    "wp.pl",
    "o2.pl",
    "onet.pl",
    "interia.pl",
}


async def signed_in(session: AsyncSession, user: User) -> SignedIn:
    return SignedIn(token=await issue_token(session, user.id), user=employee(user))


def slug(name: str) -> str:
    """A URL-safe name for the organization, with a random tail, so two
    organizations with the same name get different ones."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    return f"{base}-{secrets.token_hex(3)}"


def name_from_email(email: str) -> str:
    """eve.adams@acme.com is Eve Adams."""
    local = email.partition("@")[0]
    return " ".join(part.capitalize() for part in re.split(r"[._+-]+", local) if part)


def organization_name(email: str, name: str) -> str:
    """The company's domain, or the user's first name for a public one."""
    domain = email.partition("@")[2]
    if domain not in PUBLIC_DOMAINS:
        return domain
    return f"{name.split()[0]}'s organization"


async def user_for(session: AsyncSession, email: str, name: str | None) -> User:
    """The user with this email. One who has none yet gets an account, and a
    new organization that they administer."""
    user = await session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    name = name or name_from_email(email) or email
    org_name = organization_name(email, name)
    org = Organization(slug=slug(org_name), name=org_name)
    session.add(org)
    await session.flush()
    user = User(email=email, name=name, org_id=org.id, clearance_level=PRIVILEGED)
    session.add(user)
    await session.commit()
    return user


@router.post(
    "/email",
    summary="Email a sign-in code",
    description=(
        "Emails a six-digit code to sign in with at `/api/auth/email/verify`. "
        "The answer is the same whether or not the email has an account. The "
        "demo account's email signs in at once instead."
    ),
    responses={
        429: {"description": "A code was sent to this email moments ago."},
        503: {"description": "Email sign-in is off or the mail failed."},
    },
)
async def email(request: EmailSignIn, session: Session) -> CodeSent | SignedIn:
    if request.email == settings.demo_email:
        return await demo(session)
    if not settings.smtp_host:
        raise HTTPException(503, "Email sign-in is off")
    code = await new_code(session, request.email)
    if code is None:
        raise HTTPException(429, "A code was just sent. Check your email.")
    minutes = settings.email_code_minutes
    # The mail goes to the email's owner, so saying whether it has an
    # account tells no one else anything.
    known = await session.scalar(select(User.id).where(User.email == request.email))
    subject = "Sign in to Portcullis" if known else "Welcome to Portcullis"
    text = (
        f"Your Portcullis sign-in code is {code}.\n\n"
        f"It works for {minutes} minutes. If you didn't ask for it, ignore "
        "this email."
    )
    try:
        await send_mail(request.email, subject, text)
    except MailError as error:
        raise HTTPException(503, "The email didn't go out. Try again.") from error
    return CodeSent()


@router.post(
    "/email/verify",
    summary="Sign in with the code from the email",
    responses={401: {"description": "The code is wrong, used or expired."}},
)
async def verify_email(request: EmailCode, session: Session) -> SignedIn:
    if not await use_code(session, request.email, request.code):
        raise HTTPException(401, "Wrong or expired code")
    return await signed_in(session, await user_for(session, request.email, None))


@router.post(
    "/google",
    summary="Sign in with Google",
    description=(
        "Takes the ID token of Sign in with Google and signs in the user with "
        "its verified email."
    ),
    responses={
        401: {"description": "Google didn't confirm who the user is."},
        404: {"description": "Google sign-in is off."},
    },
)
async def google(request: GoogleSignIn, session: Session) -> SignedIn:
    if not settings.google_client_id:
        raise HTTPException(404, "Google sign-in is off")
    try:
        identity = await verify_google(request.credential, settings.google_client_id)
    except GoogleTokenError as error:
        raise HTTPException(401, "Google didn't confirm who you are") from error
    user = await user_for(session, identity.email, identity.name)
    return await signed_in(session, user)


@router.post(
    "/demo",
    summary="Sign in to the demo",
    description=(
        "Signs in as the demo account of the Golden Socks demo organization, "
        "which `./dev seed` creates."
    ),
    responses={404: {"description": "The demo hasn't been seeded."}},
)
async def demo(session: Session) -> SignedIn:
    user = await session.scalar(select(User).where(User.email == settings.demo_email))
    if user is None:
        raise HTTPException(404, "The demo isn't set up. Run ./dev seed.")
    return await signed_in(session, user)


@router.post("/sign-out", status_code=204, summary="Sign out")
async def sign_out(session: Session, authorization: Authorization = None) -> Response:
    if token := bearer_token(authorization):
        await revoke_token(session, token)
    return Response(status_code=204)
