import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PRIVILEGED, Authorization, bearer_token
from app.api.endpoints.employees import employee
from app.core.config import settings
from app.core.passwords import hash_password, verify_password
from app.core.schema.auth import SignedIn, SignIn, SignUp
from app.db.auth import issue_token, revoke_token
from app.db.models import Organization, User
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]

# One message for an unknown email and a wrong password, so the answer
# doesn't tell an attacker which emails have accounts.
WRONG = "Wrong email or password"


async def signed_in(session: AsyncSession, user: User) -> SignedIn:
    return SignedIn(token=await issue_token(session, user.id), user=employee(user))


def slug(name: str) -> str:
    """A URL-safe name for the organization, with a random tail, so two
    organizations with the same name get different ones."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    return f"{base}-{secrets.token_hex(3)}"


@router.post(
    "/sign-up",
    status_code=201,
    summary="Start an organization",
    description=(
        "Creates the organization and its first user, who administers it, and "
        "signs them in. Others join it only by invitation."
    ),
    responses={409: {"description": "The email has an account already."}},
)
async def sign_up(request: SignUp, session: Session) -> SignedIn:
    if await session.scalar(select(User.id).where(User.email == request.email)):
        raise HTTPException(409, "This email has an account. Sign in instead.")
    org = Organization(slug=slug(request.organization), name=request.organization)
    session.add(org)
    await session.flush()
    user = User(
        email=request.email,
        name=request.name,
        org_id=org.id,
        clearance_level=PRIVILEGED,
        password_hash=await hash_password(request.password),
    )
    session.add(user)
    await session.commit()
    return await signed_in(session, user)


@router.post(
    "/sign-in",
    summary="Sign in with email and password",
    responses={401: {"description": WRONG}},
)
async def sign_in(request: SignIn, session: Session) -> SignedIn:
    user = await session.scalar(select(User).where(User.email == request.email))
    stored = user.password_hash if user else None
    if not await verify_password(request.password, stored) or user is None:
        raise HTTPException(401, WRONG)
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
