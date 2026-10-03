"""OpenID Connect sign-in through an organization's own identity provider:
Okta, Entra ID, Google Workspace, Keycloak, Auth0, Zitadel or any other.

It is the authorization code flow with PKCE. The browser goes to the
provider, which sends it back with a code; the backend trades the code for
tokens, checks the ID token's signature with the provider's published keys,
its issuer, audience, expiry and nonce, and reads the user's claims from the
token and from the provider's userinfo endpoint."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

# Providers rotate their keys rarely and announce new ones early, so an
# hour-old copy still checks today's tokens. An unknown key ID refetches.
REFRESH_SECONDS = 3600


class OidcError(Exception):
    """The provider didn't confirm who the user is. The message names only
    the kind of problem, never a token."""


def by_id(jwk_set: dict) -> dict[str, jwt.PyJWK]:
    """The keys of a JSON Web Key Set by their ID. A token names the key it
    was signed with, so a key without an ID is never used."""
    keys = jwt.PyJWKSet.from_dict(jwk_set).keys
    return {key.key_id: key for key in keys if key.key_id}


class SigningKeys:
    """A provider's public signing keys, fetched from its JWKS URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.keys: dict[str, jwt.PyJWK] = {}
        self.fetched = 0.0

    async def fetch(self) -> dict[str, jwt.PyJWK]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self.url)
            response.raise_for_status()
        return by_id(response.json())

    async def key(self, key_id: str) -> jwt.PyJWK:
        stale = time.monotonic() - self.fetched > REFRESH_SECONDS
        if stale or key_id not in self.keys:
            self.keys = await self.fetch()
            self.fetched = time.monotonic()
        return self.keys[key_id]


@dataclass(frozen=True)
class Provider:
    """What sign-in needs of a provider, from its discovery document."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None
    keys: SigningKeys


# One per issuer for the whole process, so documents and keys are fetched
# once an hour, not on every sign-in.
PROVIDERS: dict[str, tuple[float, Provider]] = {}


async def discover(issuer: str) -> Provider:
    """The provider's endpoints, from {issuer}/.well-known/openid-configuration."""
    cached = PROVIDERS.get(issuer)
    if cached and time.monotonic() - cached[0] < REFRESH_SECONDS:
        return cached[1]
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
        document = response.json()
        provider = Provider(
            issuer=document["issuer"],
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            userinfo_endpoint=document.get("userinfo_endpoint"),
            keys=SigningKeys(document["jwks_uri"]),
        )
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise OidcError(f"discovery failed: {type(error).__name__}") from error
    PROVIDERS[issuer] = (time.monotonic(), provider)
    return provider


@dataclass(frozen=True)
class Login:
    """One sign-in in progress: the secrets the callback checks."""

    state: str
    nonce: str
    code_verifier: str


def new_login() -> Login:
    return Login(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64),
    )


def authorization_url(
    provider: Provider,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    login: Login,
    email: str | None = None,
) -> str:
    """Where to send the browser. The email, if known, fills in the
    provider's sign-in form."""
    digest = hashlib.sha256(login.code_verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": login.state,
        "nonce": login.nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if email:
        query["login_hint"] = email
    return f"{provider.authorization_endpoint}?{urlencode(query)}"


async def claims_for_code(
    provider: Provider,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    code: str,
    login: Login,
) -> dict[str, Any]:
    """The user's claims: the checked ID token's, then userinfo's, which may
    add the email and name that some providers leave out of the token."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": login.code_verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(provider.token_endpoint, data=form)
            response.raise_for_status()
            tokens = response.json()
            claims = await checked_id_token(provider, client_id, tokens, login)
            if provider.userinfo_endpoint and tokens.get("access_token"):
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                info = await client.get(provider.userinfo_endpoint, headers=headers)
                info.raise_for_status()
                userinfo = info.json()
                # Userinfo must be about the same user as the token.
                if userinfo.get("sub") == claims["sub"]:
                    claims = {**userinfo, **claims}
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise OidcError(f"token exchange failed: {type(error).__name__}") from error
    return claims


async def checked_id_token(
    provider: Provider, client_id: str, tokens: dict[str, Any], login: Login
) -> dict[str, Any]:
    try:
        id_token = tokens["id_token"]
        key_id = jwt.get_unverified_header(id_token).get("kid") or ""
        key = await provider.keys.key(key_id)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256", "ES256", "PS256"],
            audience=client_id,
            issuer=provider.issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise OidcError(f"bad ID token: {type(error).__name__}") from error
    if claims.get("nonce") != login.nonce:
        raise OidcError("nonce mismatch")
    return claims
