"""Single sign-on through an organization's own identity provider. The
provider vouches for its users, so a user it signs in joins its organization
without an invitation, with the role that the provider's claims map to."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.auth import signed_in
from app.core.config import settings
from app.core.oidc import (
    Login,
    OidcError,
    authorization_url,
    claims_for_code,
    discover,
    new_login,
)
from app.core.schema.auth import SignedIn, SsoCallback, SsoRedirect, SsoStart
from app.db.directory import give_role, role_for, with_groups
from app.db.models import IdentityProvider, Organization, SsoLogin, User
from app.db.sandbox import outside_sandboxes
from app.db.session import get_session

router = APIRouter(prefix="/auth/sso", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]

# How long the browser may take at the provider.
LOGIN_MINUTES = 10


def state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def callback_url() -> str:
    return f"{settings.app_url.rstrip('/')}/auth/callback"


async def provider_for(session: AsyncSession, request: SsoStart) -> IdentityProvider:
    query = select(IdentityProvider).where(IdentityProvider.enabled)
    if request.organization:
        query = query.join(Organization).where(
            Organization.slug == request.organization
        )
    else:
        domain = (request.email or "").partition("@")[2]
        query = query.where(IdentityProvider.domains.contains([domain]))
    idp = await session.scalar(query)
    if idp is None:
        raise HTTPException(404, "No single sign-on is set up for this email")
    return idp


@router.post(
    "",
    summary="Start a sign-in through an organization's identity provider",
    description=(
        "Finds the provider by the email's domain, or by the organization's "
        "slug, and answers the URL to send the browser to. The provider sends "
        "it back to `/auth/callback` in the app."
    ),
    responses={
        404: {"description": "No provider for this email or organization."},
        502: {"description": "The provider couldn't be reached."},
    },
)
async def start(request: SsoStart, session: Session) -> SsoRedirect:
    idp = await provider_for(session, request)
    try:
        provider = await discover(idp.issuer)
    except OidcError as error:
        raise HTTPException(502, f"{idp.name} couldn't be reached") from error
    login = new_login()
    session.add(
        SsoLogin(
            state_hash=state_hash(login.state),
            provider_id=idp.id,
            nonce=login.nonce,
            code_verifier=login.code_verifier,
            expires_at=datetime.now(UTC) + timedelta(minutes=LOGIN_MINUTES),
        )
    )
    await session.commit()
    url = authorization_url(
        provider, idp.client_id, callback_url(), idp.scopes, login, request.email
    )
    return SsoRedirect(url=url)


@router.post(
    "/callback",
    summary="Finish a sign-in through an organization's identity provider",
    responses={
        401: {"description": "The provider didn't confirm who the user is."},
        403: {"description": "The provider's claims give the user no role."},
        409: {"description": "The email belongs to another organization."},
    },
)
async def callback(request: SsoCallback, session: Session) -> SignedIn:
    pending = await session.get(SsoLogin, state_hash(request.state))
    if pending is None or pending.expires_at < datetime.now(UTC):
        raise HTTPException(401, "This sign-in expired. Start again.")
    # Used once: a replayed callback finds nothing.
    await session.delete(pending)
    await session.commit()
    idp = await session.get(IdentityProvider, pending.provider_id)
    if idp is None or not idp.enabled:
        raise HTTPException(401, "This single sign-on is off")
    login = Login(
        state=request.state, nonce=pending.nonce, code_verifier=pending.code_verifier
    )
    try:
        provider = await discover(idp.issuer)
        claims = await claims_for_code(
            provider,
            idp.client_id,
            idp.client_secret,
            callback_url(),
            request.code,
            login,
        )
    except OidcError as error:
        raise HTTPException(401, f"{idp.name} didn't confirm who you are") from error
    email = str(claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is False:
        raise HTTPException(401, f"{idp.name} gave no verified email")
    user = await session.scalar(
        select(User).where(User.email == email, outside_sandboxes())
    )
    if user is not None and user.org_id != idp.org_id:
        raise HTTPException(409, "This email belongs to another organization")
    if user is not None and not user.active:
        raise HTTPException(403, f"{idp.name} has deactivated you")
    # The groups SCIM synced count too, as some IdPs leave them out of tokens.
    user_id = user.id if user else None
    role = role_for(await with_groups(session, user_id, claims), idp)
    if role is None:
        raise HTTPException(403, f"{idp.name} gives you no role here")
    if user is None:
        user = User(email=email, name=str(claims.get("name") or email))
        session.add(user)
    # The provider is the source of truth: each sign-in takes its role again.
    user.org_id = idp.org_id
    give_role(user, role)
    await session.commit()
    return await signed_in(session, user)
