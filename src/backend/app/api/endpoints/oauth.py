"""The consent step of the OAuth sign-in to /api/mcp: the signed-in user lets
a client, such as Claude, use Portcullis as them. See app/api/oauth.py."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from mcp.server.auth.provider import AuthorizationParams, construct_redirect_uri
from mcp.shared.auth import InvalidRedirectUriError, InvalidScopeError
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.oauth import CODE_MINUTES, mcp_url, provider
from app.core.schema.oauth import Consent, ConsentRedirect
from app.db.auth import token_hash
from app.db.models import OAuthCode
from app.db.session import get_session

router = APIRouter(prefix="/oauth", tags=["oauth"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/consent",
    summary="Let a client use Portcullis as the user",
    description=(
        "Checks the request again, then gives the client a code that it trades "
        "once, within five minutes, for a session token of the user."
    ),
    responses={400: {"description": "The client or its redirect URI is unknown."}},
)
async def consent(
    request: Consent, user: CurrentUser, session: Session, http: Request
) -> ConsentRedirect:
    client = await provider.get_client(request.client_id)
    if client is None:
        raise HTTPException(400, "Unknown client")
    try:
        redirect_uri = client.validate_redirect_uri(AnyUrl(request.redirect_uri))
        scopes = client.validate_scope(request.scope)
    except (InvalidRedirectUriError, InvalidScopeError) as error:
        raise HTTPException(400, error.message) from error

    def back(**params: str | None) -> ConsentRedirect:
        url = construct_redirect_uri(str(redirect_uri), state=request.state, **params)
        return ConsentRedirect(redirect=url)

    if not request.allow:
        return back(error="access_denied")
    # RFC 8707: a token only for this server's /api/mcp.
    if request.resource and request.resource.rstrip("/") != mcp_url(http):
        return back(error="invalid_target")
    code = secrets.token_urlsafe(32)
    params = AuthorizationParams(
        state=None,
        scopes=scopes,
        code_challenge=request.code_challenge,
        redirect_uri=redirect_uri,
        redirect_uri_provided_explicitly=request.explicit,
        resource=request.resource,
    )
    session.add(
        OAuthCode(
            code_hash=token_hash(code),
            client_id=client.client_id,
            user_id=user.id,
            params=params.model_dump(mode="json", exclude={"state"}),
            expires_at=datetime.now(UTC) + timedelta(minutes=CODE_MINUTES),
        )
    )
    await session.commit()
    return back(code=code)
