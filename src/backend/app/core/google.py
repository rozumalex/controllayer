"""Checks the ID tokens of Sign in with Google.

The browser gets a token signed by Google for our client ID. It proves who
the user is: the backend checks Google's signature with Google's public keys,
that the token is for our client ID, that it hasn't expired, and that Google
has verified the email. No client secret is involved."""

import time
from dataclasses import dataclass

import httpx
import jwt

CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["accounts.google.com", "https://accounts.google.com"]
# Google rotates its keys every few weeks and announces new ones early, so an
# hour-old copy still checks today's tokens. An unknown key ID refetches.
REFRESH_SECONDS = 3600


class GoogleTokenError(Exception):
    """The token doesn't prove who the user is. The message names only the
    kind of problem, never the token."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    name: str


def by_id(jwk_set: dict) -> dict[str, jwt.PyJWK]:
    """The keys of a JSON Web Key Set by their ID. A token names the key it
    was signed with, so a key without an ID is never used."""
    keys = jwt.PyJWKSet.from_dict(jwk_set).keys
    return {key.key_id: key for key in keys if key.key_id}


class GoogleKeys:
    """Google's public signing keys, shared by the process."""

    def __init__(self, url: str = CERTS_URL) -> None:
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


GOOGLE_KEYS = GoogleKeys()


async def verify(
    credential: str, client_id: str, keys: GoogleKeys = GOOGLE_KEYS
) -> GoogleIdentity:
    """Who the token says the user is, or GoogleTokenError."""
    try:
        key_id = jwt.get_unverified_header(credential).get("kid") or ""
        key = await keys.key(key_id)
        claims = jwt.decode(
            credential,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "email"]},
        )
    except (jwt.PyJWTError, KeyError, httpx.HTTPError, ValueError) as error:
        raise GoogleTokenError(type(error).__name__) from error
    if claims.get("email_verified") is not True:
        raise GoogleTokenError("email not verified")
    email = str(claims["email"]).lower()
    return GoogleIdentity(email=email, name=str(claims.get("name") or email))
