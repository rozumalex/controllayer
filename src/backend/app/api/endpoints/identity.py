"""The organization's identity provider, which its admins connect on the
Identity page. Every endpoint works on the signed-in admin's organization."""

import hashlib
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgId
from app.api.endpoints.sso import callback_url, discover
from app.core.config import settings
from app.core.oidc import OidcError
from app.core.schema.identity import (
    DirectoryEventRead,
    DirectoryGroupRead,
    IdentityProviderRead,
    IdentityProviderWrite,
    ScimStatus,
    ScimToken,
)
from app.db.directory import role_for
from app.db.models import (
    DirectoryEvent,
    DirectoryGroup,
    IdentityProvider,
    Organization,
    group_members,
)
from app.db.session import get_session

router = APIRouter(prefix="/identity-provider", tags=["identity"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def own_provider(session: AsyncSession, org_id: OrgId) -> IdentityProvider | None:
    return await session.scalar(
        select(IdentityProvider).where(IdentityProvider.org_id == org_id)
    )


@router.get(
    "",
    summary="Show the organization's identity provider",
    description="null when the organization has none. The client secret is "
    "never returned.",
)
async def get_provider(session: Session, org_id: OrgId) -> IdentityProviderRead | None:
    idp = await own_provider(session, org_id)
    return IdentityProviderRead.of(idp, callback_url()) if idp else None


@router.put(
    "",
    summary="Connect or update the organization's identity provider",
    description=(
        "The control layer reads the provider's discovery document first, so "
        "an issuer it can't reach is refused with 422. An email domain another "
        "organization's provider has is refused with 409."
    ),
)
async def save_provider(
    request: IdentityProviderWrite, session: Session, org_id: OrgId
) -> IdentityProviderRead:
    issuer = str(request.issuer).rstrip("/")
    try:
        await discover(issuer)
    except OidcError as error:
        raise HTTPException(
            422, f"Can't read {issuer}'s OpenID configuration"
        ) from error
    for domain in request.domains:
        taken = await session.scalar(
            select(IdentityProvider.id).where(
                IdentityProvider.org_id != org_id,
                IdentityProvider.domains.contains([domain]),
            )
        )
        if taken:
            raise HTTPException(409, f"Another organization signs in {domain}")
    idp = await own_provider(session, org_id)
    if idp is None:
        idp = IdentityProvider(org_id=org_id)
        session.add(idp)
    idp.name = request.name
    idp.issuer = issuer
    idp.client_id = request.client_id
    idp.scopes = request.scopes
    idp.domains = request.domains
    idp.role_rules = [rule.model_dump() for rule in request.role_rules]
    idp.default_role = request.default_role
    idp.enabled = request.enabled
    if request.client_secret is not None:
        idp.client_secret = request.client_secret or None
    await session.commit()
    return IdentityProviderRead.of(idp, callback_url())


def scim_base_url() -> str:
    return f"{settings.app_url.rstrip('/')}{settings.api_prefix}/scim/v2"


@router.get("/scim", summary="Show the SCIM base URL and whether a token is set")
async def scim_status(session: Session, org_id: OrgId) -> ScimStatus:
    org = await session.get(Organization, org_id)
    assert org is not None
    last = await session.scalar(
        select(func.max(DirectoryEvent.created_at)).where(
            DirectoryEvent.org_id == org_id
        )
    )
    return ScimStatus(
        base_url=scim_base_url(),
        has_token=bool(org.scim_token_hash),
        last_sync_at=last,
    )


@router.get("/groups", summary="The groups the IdP synced, with their roles")
async def list_groups(session: Session, org_id: OrgId) -> list[DirectoryGroupRead]:
    idp = await own_provider(session, org_id)
    rows = await session.execute(
        select(DirectoryGroup.display_name, func.count(group_members.c.user_id))
        .outerjoin(group_members, group_members.c.group_id == DirectoryGroup.id)
        .where(DirectoryGroup.org_id == org_id)
        .group_by(DirectoryGroup.id)
        .order_by(DirectoryGroup.display_name)
    )
    groups = []
    for name, members in rows:
        role = role_for({"groups": [name]}, idp) if idp else None
        groups.append(
            DirectoryGroupRead(
                name=name, role=role[0] if role else None, members=members
            )
        )
    return groups


@router.get("/log", summary="The provisioning log, newest first")
async def provisioning_log(
    session: Session, org_id: OrgId, limit: int = 50
) -> list[DirectoryEventRead]:
    events = await session.scalars(
        select(DirectoryEvent)
        .where(DirectoryEvent.org_id == org_id)
        .order_by(DirectoryEvent.id.desc())
        .limit(min(limit, 200))
    )
    return [
        DirectoryEventRead(
            id=e.id,
            kind=e.kind,
            at=e.created_at,
            name=e.user.name if e.user else None,
            email=e.user.email if e.user else None,
            data=e.data,
        )
        for e in events
    ]


@router.post(
    "/scim-token",
    summary="Make a new SCIM token for the IdP's provisioning",
    description=(
        "The IdP pushes the organization's users and groups to `/api/scim/v2` "
        "with it. Shown once and stored as a hash; a new one replaces the old."
    ),
)
async def new_scim_token(session: Session, org_id: OrgId) -> ScimToken:
    token = f"scim_{secrets.token_urlsafe(32)}"
    org = await session.get(Organization, org_id)
    assert org is not None
    org.scim_token_hash = hashlib.sha256(token.encode()).hexdigest()
    await session.commit()
    return ScimToken(token=token, base_url=scim_base_url())


@router.delete(
    "", status_code=204, summary="Disconnect the organization's identity provider"
)
async def delete_provider(session: Session, org_id: OrgId) -> Response:
    if idp := await own_provider(session, org_id):
        await session.delete(idp)
        await session.commit()
    return Response(status_code=204)
