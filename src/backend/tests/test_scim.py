import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.auth import issue_token
from app.db.models import IdentityProvider, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id

SCIM = "/api/scim/v2"
RULES = [
    {
        "claim": "groups",
        "value": "sg-ai-compliance",
        "role": "Compliance Officer",
        "admin": True,
    },
    {"claim": "groups", "value": "sg-ai-analysts", "role": "Analyst", "admin": False},
]


async def add_idp() -> None:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        session.add(
            IdentityProvider(
                org_id=org_id,
                name="Okta",
                issuer="https://acme.okta.com",
                client_id="x",
                scopes="openid",
                domains=[],
                role_rules=RULES,
            )
        )
        await session.commit()


@pytest.fixture
def okta(db: None, client: TestClient) -> TestClient:
    """A client signed in with the demo organization's SCIM token, as Okta's
    provisioning would be."""
    asyncio.run(add_idp())
    token = client.post("/api/identity-provider/scim-token").json()["token"]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def new_user(okta: TestClient, email: str = "Eve@Acme.com") -> dict[str, Any]:
    body = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": email,
        "name": {"givenName": "Eve", "familyName": "Acme"},
        "emails": [{"value": email, "primary": True}],
        "externalId": "00u1",
        "active": True,
    }
    response = okta.post(f"{SCIM}/Users", json=body)
    assert response.status_code == 201
    return response.json()


def new_group(okta: TestClient, name: str, *members: str) -> dict[str, Any]:
    body = {"displayName": name, "members": [{"value": m} for m in members]}
    response = okta.post(f"{SCIM}/Groups", json=body)
    assert response.status_code == 201
    return response.json()


async def stored(email: str) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        return user


def test_unknown_token_is_401_in_scim_format(db: None) -> None:
    # when
    response = TestClient(app).get(f"{SCIM}/Users")

    # then
    assert response.status_code == 401
    assert response.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]


def test_token_is_shown_once_with_the_base_url(client: TestClient) -> None:
    # when
    body = client.post("/api/identity-provider/scim-token").json()

    # then
    assert body["token"].startswith("scim_")
    assert body["base_url"] == "http://localhost:3000/api/scim/v2"


def test_status_says_whether_a_token_is_set(db: None, client: TestClient) -> None:
    # given
    url = "/api/identity-provider/scim"
    before = client.get(url).json()

    # when
    client.post("/api/identity-provider/scim-token")

    # then
    assert before["base_url"] == "http://localhost:3000/api/scim/v2"
    assert before["has_token"] is False
    assert client.get(url).json()["has_token"] is True


def test_pushed_user_joins_the_organization(okta: TestClient) -> None:
    # when
    user = new_user(okta)

    # then
    assert user["userName"] == "eve@acme.com"
    assert user["displayName"] == "Eve Acme"
    found = okta.get(f"{SCIM}/Users", params={"filter": 'userName eq "eve@acme.com"'})
    assert found.json()["totalResults"] == 1
    assert found.headers["content-type"].startswith("application/scim+json")


def test_group_membership_sets_the_role(okta: TestClient) -> None:
    # given
    user = new_user(okta)

    # when
    new_group(okta, "sg-ai-compliance", user["id"])

    # then
    stored_user = asyncio.run(stored("eve@acme.com"))
    assert (stored_user.title, stored_user.clearance_level) == (
        "Compliance Officer",
        "PRIVILEGED",
    )


def test_moving_groups_changes_the_role(okta: TestClient) -> None:
    # given
    user = new_user(okta)
    compliance = new_group(okta, "sg-ai-compliance", user["id"])
    analysts = new_group(okta, "sg-ai-analysts")

    # when
    remove = f'members[value eq "{user["id"]}"]'
    okta.patch(
        f"{SCIM}/Groups/{compliance['id']}",
        json={"Operations": [{"op": "remove", "path": remove}]},
    )
    okta.patch(
        f"{SCIM}/Groups/{analysts['id']}",
        json={
            "Operations": [
                {"op": "add", "path": "members", "value": [{"value": user["id"]}]}
            ]
        },
    )

    # then
    stored_user = asyncio.run(stored("eve@acme.com"))
    assert (stored_user.title, stored_user.clearance_level) == ("Analyst", "STANDARD")


def test_user_with_no_mapped_group_works_under_the_default_policy(
    okta: TestClient,
) -> None:
    # given
    user = new_user(okta)
    group = new_group(okta, "sg-ai-compliance", user["id"])

    # when
    okta.delete(f"{SCIM}/Groups/{group['id']}")

    # then
    assert asyncio.run(stored("eve@acme.com")).title is None


def test_deactivated_user_loses_their_sessions(okta: TestClient) -> None:
    # given
    user = new_user(okta)
    token = asyncio.run(session_token("eve@acme.com"))
    headers = {"Authorization": f"Bearer {token}"}
    assert TestClient(app).get("/api/employees/me", headers=headers).status_code == 200

    # when
    okta.patch(
        f"{SCIM}/Users/{user['id']}",
        json={"Operations": [{"op": "replace", "value": {"active": False}}]},
    )

    # then
    assert TestClient(app).get("/api/employees/me", headers=headers).status_code == 401
    assert okta.get(f"{SCIM}/Users/{user['id']}").json()["active"] is False


async def session_token(email: str) -> str:
    user = await stored(email)
    async with SessionLocal() as session:
        return await issue_token(session, user.id)


def test_entra_style_deactivation(okta: TestClient) -> None:
    # given
    user = new_user(okta)

    # when
    okta.patch(
        f"{SCIM}/Users/{user['id']}",
        json={"Operations": [{"op": "Replace", "path": "active", "value": "False"}]},
    )

    # then
    assert asyncio.run(stored("eve@acme.com")).active is False


def test_deleted_user_is_kept_deactivated(okta: TestClient) -> None:
    # given
    user = new_user(okta)

    # when
    response = okta.delete(f"{SCIM}/Users/{user['id']}")

    # then
    assert response.status_code == 204
    assert asyncio.run(stored("eve@acme.com")).active is False


def test_people_list_shows_deactivated_users(
    okta: TestClient, client: TestClient
) -> None:
    # given
    user = new_user(okta)
    new_group(okta, "sg-ai-analysts", user["id"])
    okta.delete(f"{SCIM}/Users/{user['id']}")

    # when
    people = client.get("/api/employees", params={"q": "eve@acme.com"}).json()

    # then
    assert [e["active"] for e in people["employees"]] == [False]


def test_taken_user_name_is_409(okta: TestClient) -> None:
    # given
    new_user(okta)

    # when
    response = okta.post(f"{SCIM}/Users", json={"userName": "eve@acme.com"})

    # then
    assert response.status_code == 409
    assert response.json()["scimType"] == "uniqueness"


def test_user_of_another_organization_is_404(okta: TestClient, user: User) -> None:
    # given
    other = "00000000-0000-0000-0000-000000000000"

    # when / then
    assert okta.get(f"{SCIM}/Users/{other}").status_code == 404


def test_service_provider_config(okta: TestClient) -> None:
    # when
    config = okta.get(f"{SCIM}/ServiceProviderConfig").json()

    # then
    assert config["patch"]["supported"] is True
    assert config["authenticationSchemes"][0]["type"] == "oauthbearertoken"


def test_log_follows_a_user_from_joiner_to_leaver(
    okta: TestClient, client: TestClient
) -> None:
    # given
    user = new_user(okta)
    asyncio.run(session_token("eve@acme.com"))
    analysts = new_group(okta, "sg-ai-analysts", user["id"])
    compliance = new_group(okta, "sg-ai-compliance")

    # when
    okta.patch(
        f"{SCIM}/Groups/{analysts['id']}",
        json={
            "Operations": [
                {"op": "remove", "path": f'members[value eq "{user["id"]}"]'}
            ]
        },
    )
    okta.patch(
        f"{SCIM}/Groups/{compliance['id']}",
        json={
            "Operations": [
                {"op": "add", "path": "members", "value": [{"value": user["id"]}]}
            ]
        },
    )
    okta.delete(f"{SCIM}/Users/{user['id']}")

    # then
    log = client.get("/api/identity-provider/log").json()
    assert [(e["kind"], e["data"]) for e in reversed(log)] == [
        ("created", {}),
        ("joined", {"group": "sg-ai-analysts"}),
        ("role", {"role": "Analyst", "was": None}),
        ("left", {"group": "sg-ai-analysts"}),
        ("role", {"role": None, "was": "Analyst"}),
        ("joined", {"group": "sg-ai-compliance"}),
        ("role", {"role": "Compliance Officer", "was": None}),
        ("deactivated", {"sessions": 1}),
    ]
    assert {e["email"] for e in log} == {"eve@acme.com"}


def test_groups_show_their_role_and_members(
    okta: TestClient, client: TestClient
) -> None:
    # given
    user = new_user(okta)
    new_group(okta, "sg-ai-analysts", user["id"])
    new_group(okta, "sg-unmapped")

    # when
    groups = client.get("/api/identity-provider/groups").json()

    # then
    assert groups == [
        {"name": "sg-ai-analysts", "role": "Analyst", "members": 1},
        {"name": "sg-unmapped", "role": None, "members": 0},
    ]
