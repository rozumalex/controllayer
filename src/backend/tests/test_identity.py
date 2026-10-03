import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.endpoints import identity
from app.core.oidc import OidcError
from app.db.models import IdentityProvider, Organization
from app.db.session import SessionLocal
from tests.test_sso import PROVIDER

pytestmark = pytest.mark.usefixtures("db")

URL = "/api/identity-provider"
OKTA = {
    "name": "Acme Okta",
    "issuer": "https://acme.okta.com/",
    "client_id": "controllayer",
    "client_secret": "s3cret",
    "domains": ["@Acme.com", "acme.io"],
    "role_rules": [
        {"claim": "groups", "value": "sg-ai", "role": "Analyst", "admin": False}
    ],
    "default_role": "",
    "scopes": "profile email",
}


@pytest.fixture(autouse=True)
def reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def discover(issuer: str) -> Any:
        return PROVIDER

    monkeypatch.setattr(identity, "discover", discover)


def test_no_provider_is_null(client: TestClient) -> None:
    # when / then
    assert client.get(URL).json() is None


def test_connect_a_provider(client: TestClient) -> None:
    # when
    saved = client.put(URL, json=OKTA)

    # then
    assert saved.status_code == 200
    body = client.get(URL).json()
    assert body["issuer"] == "https://acme.okta.com"
    assert body["domains"] == ["acme.com", "acme.io"]
    assert body["scopes"] == "openid profile email"
    assert body["default_role"] is None
    assert body["redirect_uri"] == "http://localhost:3000/auth/callback"
    assert body["has_secret"] is True
    assert "s3cret" not in saved.text


def test_secret_left_out_is_kept(client: TestClient) -> None:
    # given
    client.put(URL, json=OKTA)

    # when
    body = client.put(URL, json={**OKTA, "client_secret": None}).json()

    # then
    assert body["has_secret"] is True


def test_empty_secret_removes_it(client: TestClient) -> None:
    # given
    client.put(URL, json=OKTA)

    # when
    body = client.put(URL, json={**OKTA, "client_secret": ""}).json()

    # then
    assert body["has_secret"] is False


def test_unreachable_issuer_is_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    async def discover(issuer: str) -> Any:
        raise OidcError("discovery failed")

    monkeypatch.setattr(identity, "discover", discover)

    # when / then
    assert client.put(URL, json=OKTA).status_code == 422


def test_domain_of_another_organization_is_409(client: TestClient) -> None:
    # given
    asyncio.run(other_provider(["acme.com"]))

    # when / then
    assert client.put(URL, json=OKTA).status_code == 409


async def other_provider(domains: list[str]) -> None:
    async with SessionLocal() as session:
        org = Organization(slug="rival", name="Rival")
        session.add(org)
        await session.flush()
        session.add(
            IdentityProvider(
                org_id=org.id,
                name="Rival",
                issuer="https://rival.test",
                client_id="x",
                scopes="openid",
                domains=domains,
                role_rules=[],
            )
        )
        await session.commit()


def test_disconnect(client: TestClient) -> None:
    # given
    client.put(URL, json=OKTA)

    # when
    client.delete(URL)

    # then
    assert client.get(URL).json() is None


def test_another_organizations_provider_is_not_shown(client: TestClient) -> None:
    # given
    asyncio.run(other_provider(["rival.com"]))

    # when / then
    assert client.get(URL).json() is None


def test_idp_roles_are_listed_for_policies(client: TestClient) -> None:
    # given
    client.put(URL, json={**OKTA, "default_role": "Guest"})

    # when
    roles = {r["role"]: r for r in client.get("/api/policy").json()["roles"]}

    # then
    assert roles["Analyst"]["employees"] == 0
    assert roles["Analyst"]["from_idp"] is True
    assert roles["Guest"]["from_idp"] is True


def test_idp_role_gets_its_policy_before_anyone_signs_in(client: TestClient) -> None:
    # given
    client.put(URL, json=OKTA)
    policy = client.get("/api/policy").json()["default"]["settings"]

    # when
    saved = client.put("/api/policy/roles/Analyst", json=policy)

    # then
    assert saved.status_code == 200
    roles = {r["role"]: r for r in client.get("/api/policy").json()["roles"]}
    assert roles["Analyst"]["customized"] is True


def test_role_nobody_has_and_no_idp_gives_is_404(client: TestClient) -> None:
    # given
    policy = client.get("/api/policy").json()["default"]["settings"]

    # when / then
    assert client.put("/api/policy/roles/Pilot", json=policy).status_code == 404
