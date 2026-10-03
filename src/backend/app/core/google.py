"""Checks the ID tokens of Sign in with Google.

The browser gets a token signed by Google for our client ID. It proves who
the user is: the backend checks Google's signature with Google's public keys,
that the token is for our client ID, that it hasn't expired, and that Google
has verified the email. No client secret is involved."""

from dataclasses import dataclass

import httpx
import jwt

from app.core.oidc import SigningKeys

CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["accounts.google.com", "https://accounts.google.com"]


class GoogleTokenError(Exception):
    """The token doesn't prove who the user is. The message names only the
    kind of problem, never the token."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    name: str


GOOGLE_KEYS = SigningKeys(CERTS_URL)


async def verify(
    credential: str, client_id: str, keys: SigningKeys = GOOGLE_KEYS
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
