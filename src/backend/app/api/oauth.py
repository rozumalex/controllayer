"""OAuth for /api/mcp, as the MCP authorization spec asks, so a client such
as Claude signs the user in by itself: the user pastes the MCP URL, signs in
to Portcullis in the browser and approves the client, and the client gets a
session token of that user.

The MCP SDK's handlers check the requests, such as the redirect URI and the
PKCE verifier, and this module stores the clients and the codes. The
metadata names this server's own address, read from each request, as the
same API serves localhost, an ngrok tunnel and production.
"""

from datetime import UTC, datetime
from urllib.parse import urlencode

from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import cors_middleware
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from sqlalchemy import delete
from starlette.requests import HTTPConnection, Request
from starlette.responses import Response
from starlette.routing import Route

from app.core.config import settings
from app.db.auth import issue_token, token_hash
from app.db.models import OAuthClient, OAuthCode
from app.db.session import SessionLocal

OAUTH = f"{settings.api_prefix}/oauth"
MCP_PATH = f"{settings.api_prefix}/mcp"
# The consent page of the frontend.
CONSENT_PATH = "/oauth/authorize"
# How long a client has to trade a code for a token.
CODE_MINUTES = 5


def origin(connection: HTTPConnection) -> str:
    """The address the client sees, behind the Vite proxy, ngrok or the
    DigitalOcean ingress."""
    headers = connection.headers
    scheme = headers.get("x-forwarded-proto", connection.url.scheme)
    host = headers.get("x-forwarded-host") or headers.get("host", "")
    return f"{scheme.split(',')[0].strip()}://{host.split(',')[0].strip()}"


def mcp_url(connection: HTTPConnection) -> str:
    """The MCP server's URL: the resource every token is for."""
    return origin(connection) + MCP_PATH


def resource_metadata_url(connection: HTTPConnection) -> str:
    return f"{origin(connection)}/.well-known/oauth-protected-resource{MCP_PATH}"


class Provider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """The SDK's view of the clients and the codes. There are no refresh
    tokens: the session token lasts AUTH_SESSION_DAYS, then the client signs
    the user in again."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with SessionLocal() as session:
            client = await session.get(OAuthClient, client_id)
        if client is None:
            return None
        return OAuthClientInformationFull.model_validate(client.info)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # A public client, so there is no secret to keep. The handler sends
        # back this same record, so the client learns it too.
        client_info.token_endpoint_auth_method = "none"
        client_info.client_secret = None
        client_info.client_secret_expires_at = None
        info = client_info.model_dump(mode="json", exclude_none=True)
        async with SessionLocal() as session:
            session.add(OAuthClient(client_id=client_info.client_id, info=info))
            await session.commit()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """The consent page, which signs the user in first and then sends
        the request on to /api/oauth/consent."""
        query = {
            "client_id": client.client_id,
            "client_name": client.client_name or "",
            "redirect_uri": str(params.redirect_uri),
            "explicit": "1" if params.redirect_uri_provided_explicitly else "",
            "code_challenge": params.code_challenge,
            "state": params.state or "",
            "scope": " ".join(params.scopes or []),
            "resource": params.resource or "",
        }
        return f"{CONSENT_PATH}?{urlencode({k: v for k, v in query.items() if v})}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with SessionLocal() as session:
            code = await session.get(OAuthCode, token_hash(authorization_code))
        if code is None or code.client_id != client.client_id:
            return None
        return AuthorizationCode.model_validate(
            {
                **code.params,
                "scopes": code.params.get("scopes") or [],
                "code": authorization_code,
                "client_id": code.client_id,
                "expires_at": code.expires_at.timestamp(),
                "subject": str(code.user_id),
            }
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Deleting it first makes the code work once, even for two requests
        # at the same time.
        async with SessionLocal() as session:
            user_id = await session.scalar(
                delete(OAuthCode)
                .where(
                    OAuthCode.code_hash == token_hash(authorization_code.code),
                    OAuthCode.expires_at > datetime.now(UTC),
                )
                .returning(OAuthCode.user_id)
            )
            if user_id is None:
                raise TokenError("invalid_grant", "The code was used or expired")
            token = await issue_token(session, user_id)
        return OAuthToken(
            access_token=token, expires_in=settings.auth_session_days * 86400
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError("invalid_grant", "There are no refresh tokens")

    async def load_access_token(self, token: str) -> AccessToken | None:
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        return None


provider = Provider()


async def protected_resource(request: Request) -> Response:
    """RFC 9728: /api/mcp takes tokens from this server."""
    # From plain strings, so an origin keeps no trailing slash: clients
    # compare the issuer as a string.
    metadata = ProtectedResourceMetadata.model_validate(
        {
            "resource": mcp_url(request),
            "authorization_servers": [origin(request)],
            "resource_name": "Portcullis",
        }
    )
    return PydanticJSONResponse(metadata)


async def authorization_server(request: Request) -> Response:
    """RFC 8414: where a client registers, signs the user in and gets a
    token."""
    base = origin(request) + OAUTH
    metadata = OAuthMetadata.model_validate(
        {
            "issuer": origin(request),
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "registration_endpoint": f"{base}/register",
            "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
        }
    )
    return PydanticJSONResponse(metadata)


registration = RegistrationHandler(provider, ClientRegistrationOptions(enabled=True))
token = TokenHandler(provider, ClientAuthenticator(provider))
READ = ["GET", "OPTIONS"]
WRITE = ["POST", "OPTIONS"]

# The metadata lives at the root of the origin, where clients look for it,
# so the Vite proxy and the ingress send /.well-known to the API too. The
# other endpoints sit under the API prefix, and the metadata names them.
oauth_routes = [
    Route(
        f"/.well-known/oauth-protected-resource{MCP_PATH}",
        cors_middleware(protected_resource, READ),
        methods=READ,
    ),
    Route(
        "/.well-known/oauth-protected-resource",
        cors_middleware(protected_resource, READ),
        methods=READ,
    ),
    Route(
        "/.well-known/oauth-authorization-server",
        cors_middleware(authorization_server, READ),
        methods=READ,
    ),
    # The browser opens it, so it needs no CORS.
    Route(
        f"{OAUTH}/authorize",
        AuthorizationHandler(provider).handle,
        methods=["GET", "POST"],
    ),
    Route(f"{OAUTH}/token", cors_middleware(token.handle, WRITE), methods=WRITE),
    Route(
        f"{OAUTH}/register",
        cors_middleware(registration.handle, WRITE),
        methods=WRITE,
    ),
]
