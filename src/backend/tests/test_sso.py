import asyncio
import json
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select

from app.api.endpoints import sso
from app.core import oidc
from app.db.models import IdentityProvider, Organization, User
from app.db.session import SessionLocal
from app.main import app

pytestmark = pytest.mark.usefixtures("db")

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISSUER = "https://idp.acme.test"
RULES = [
    {
        "claim": "groups",
        "value": "sg-ai-compliance",
        "role": "Compliance Officer",
        "admin": True,
    },
    {"claim": "sub", "value": "2", "role": "Analyst", "admin": False},
]


class FakeKeys(oidc.SigningKeys):
    async def fetch(self) -> dict[str, jwt.PyJWK]:
        public = json.loads(RSAAlgorithm.to_jwk(KEY.public_key()))
        return oidc.by_id({"keys": [{**public, "kid": "k1", "alg": "RS256"}]})


PROVIDER = oidc.Provider(
    issuer=ISSUER,
    authorization_endpoint=f"{ISSUER}/authorize",
    token_endpoint=f"{ISSUER}/token",
    userinfo_endpoint=None,
    keys=FakeKeys(f"{ISSUER}/jwks"),
)


async def add_provider(**changes: Any) -> uuid.UUID:
    async with SessionLocal() as session:
        org = Organization(slug="acme", name="Acme")
        session.add(org)
        await session.flush()
        values = {
            "name": "Acme Okta",
            "issuer": ISSUER,
            "client_id": "controllayer",
            "scopes": "openid profile email",
            "domains": ["acme.com"],
            "role_rules": RULES,
            "default_role": None,
        } | changes
        session.add(IdentityProvider(org_id=org.id, **values))
        await session.commit()
        return org.id


@pytest.fixture
def provider(db: None, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    async def discover(issuer: str) -> oidc.Provider:
        return PROVIDER

    monkeypatch.setattr(sso, "discover", discover)
    return asyncio.run(add_provider())


def signs_in_as(monkeypatch: pytest.MonkeyPatch, **claims: Any) -> None:
    """The provider vouches for these claims."""

    async def claims_for_code(*args: Any) -> dict[str, Any]:
        return {"sub": "1", "email": "Eve@Acme.com", "name": "Eve Acme"} | claims

    monkeypatch.setattr(sso, "claims_for_code", claims_for_code)


def start(client: TestClient, **request: str) -> dict[str, list[str]]:
    response = client.post("/api/auth/sso", json=request)
    assert response.status_code == 200
    return parse_qs(urlparse(response.json()["url"]).query)


def finish(client: TestClient, query: dict[str, list[str]]) -> Any:
    callback = {"code": "the-code", "state": query["state"][0]}
    return client.post("/api/auth/sso/callback", json=callback)


async def stored(email: str) -> User | None:
    async with SessionLocal() as session:
        return await session.scalar(select(User).where(User.email == email))


@pytest.mark.usefixtures("provider")
def test_work_email_goes_to_its_provider() -> None:
    # when
    query = start(TestClient(app), email="eve@acme.com")

    # then
    assert query["client_id"] == ["controllayer"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["login_hint"] == ["eve@acme.com"]
    assert query["redirect_uri"] == ["http://localhost:3000/auth/callback"]


@pytest.mark.usefixtures("provider")
def test_email_without_a_provider_is_404() -> None:
    # when
    response = TestClient(app).post("/api/auth/sso", json={"email": "eve@other.com"})

    # then
    assert response.status_code == 404


def test_provider_user_joins_its_organization_with_the_mapped_role(
    provider: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    signs_in_as(monkeypatch, groups=["staff", "sg-ai-compliance"])
    client = TestClient(app)

    # when
    response = finish(client, start(client, email="eve@acme.com"))

    # then
    assert response.status_code == 200
    user = asyncio.run(stored("eve@acme.com"))
    assert user is not None and user.org_id == provider
    assert (user.title, user.clearance_level) == ("Compliance Officer", "PRIVILEGED")


@pytest.mark.usefixtures("provider")
def test_each_sign_in_takes_the_role_again(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    client = TestClient(app)
    signs_in_as(monkeypatch, groups=["sg-ai-compliance"])
    finish(client, start(client, email="eve@acme.com"))
    signs_in_as(monkeypatch, sub="2", groups=[])

    # when
    finish(client, start(client, email="eve@acme.com"))

    # then
    user = asyncio.run(stored("eve@acme.com"))
    assert user is not None
    assert (user.title, user.clearance_level) == ("Analyst", "STANDARD")


@pytest.mark.usefixtures("provider")
def test_callback_works_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    signs_in_as(monkeypatch, groups=["sg-ai-compliance"])
    client = TestClient(app)
    query = start(client, email="eve@acme.com")
    finish(client, query)

    # when / then
    assert finish(client, query).status_code == 401


@pytest.mark.usefixtures("provider")
def test_unknown_state_is_401() -> None:
    # when
    response = finish(TestClient(app), {"state": ["made-up"]})

    # then
    assert response.status_code == 401


@pytest.mark.usefixtures("provider")
@pytest.mark.parametrize(
    ("claims", "status"),
    [
        pytest.param({"groups": ["staff"], "sub": "9"}, 403, id="no role"),
        pytest.param(
            {"email_verified": False, "groups": ["sg-ai-compliance"]},
            401,
            id="unverified",
        ),
        pytest.param({"email": None}, 401, id="no email"),
    ],
)
def test_sign_in_refused(
    monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any], status: int
) -> None:
    # given
    signs_in_as(monkeypatch, **claims)
    client = TestClient(app)

    # when / then
    assert finish(client, start(client, email="eve@acme.com")).status_code == status


@pytest.mark.usefixtures("provider")
def test_email_of_another_organization_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    signs_in_as(monkeypatch, email="tester@example.com", groups=["sg-ai-compliance"])
    client = TestClient(app)
    asyncio.run(other_member("tester@example.com"))

    # when / then
    assert finish(client, start(client, email="eve@acme.com")).status_code == 409


async def other_member(email: str) -> None:
    async with SessionLocal() as session:
        org = Organization(slug="other", name="Other")
        session.add(org)
        await session.flush()
        session.add(User(email=email, name="Other", org_id=org.id))
        await session.commit()


def id_token(nonce: str, /, **changes: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "controllayer",
        "sub": "1",
        "iat": now,
        "exp": now + 300,
        "nonce": nonce,
    } | changes
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})


def test_id_token_from_the_provider_is_accepted() -> None:
    # given
    login = oidc.new_login()
    tokens = {"id_token": id_token(login.nonce)}

    # when
    claims = asyncio.run(oidc.checked_id_token(PROVIDER, "controllayer", tokens, login))

    # then
    assert claims["sub"] == "1"


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"nonce": "replayed"}, id="nonce"),
        pytest.param({"aud": "another-app"}, id="audience"),
        pytest.param({"iss": "https://evil.test"}, id="issuer"),
        pytest.param({"exp": int(time.time()) - 60}, id="expired"),
    ],
)
def test_id_token_the_provider_did_not_vouch_for_is_refused(
    changes: dict[str, Any],
) -> None:
    # given
    login = oidc.new_login()
    tokens = {"id_token": id_token(login.nonce, **changes)}

    # when / then
    with pytest.raises(oidc.OidcError):
        asyncio.run(oidc.checked_id_token(PROVIDER, "controllayer", tokens, login))
