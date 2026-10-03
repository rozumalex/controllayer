"""The organization's identity provider, which its admins connect on the
Identity page. Every endpoint works on the signed-in admin's organization."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgId
from app.api.endpoints.sso import callback_url, discover
from app.core.oidc import OidcError
from app.core.schema.identity import IdentityProviderRead, IdentityProviderWrite
from app.db.models import IdentityProvider
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


@router.delete(
    "", status_code=204, summary="Disconnect the organization's identity provider"
)
async def delete_provider(session: Session, org_id: OrgId) -> Response:
    if idp := await own_provider(session, org_id):
        await session.delete(idp)
        await session.commit()
    return Response(status_code=204)
