import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import mcp_gateway
from app.core.config import settings
from app.db.models import Policy, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id, signed_in
from tests.test_mcp_gateway import gateway

URL = "/api/policy"
POLICY: dict[str, Any] = {
    "injection_threshold": 0.5,
    "clearance": "CONFIDENTIAL",
    "above_clearance": "block",
    "allowed_models": ["gpt-4.1", "gpt-4.1-mini"],
    "budget": {"monthly_tokens": 100000, "monthly_usd": "25.00"},
    "default_tool_action": "block",
    "tools": {"bank__get_client": "redact"},
}


async def add_staff() -> None:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        session.add_all(
            [
                User(email="ann@goldensocks.com", name="Ann Lee", title="Analyst"),
                User(email="bob@goldensocks.com", name="Bob Ray", title="Analyst"),
                User(email="cy@goldensocks.com", name="Cy Fox", title="Engineer"),
                User(email="guest@example.com", name="A Guest"),
            ]
        )
        for staff in session.new:
            staff.org_id = org_id
        await session.commit()


@pytest.fixture
def staff(db: None, user: User) -> Iterator[TestClient]:
    asyncio.run(add_staff())
    with TestClient(app, headers=signed_in(user)) as client:
        yield client


def roles(overview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {role["role"]: role for role in overview["roles"]}


def test_roles_follow_the_builtin_default(staff: TestClient) -> None:
    # when
    overview = staff.get(URL).json()

    # then
    assert overview["default"]["customized"] is False
    assert overview["default"]["settings"]["allowed_models"] == sorted(
        settings.chat_models
    )
    assert {r: v["employees"] for r, v in roles(overview).items()} == {
        "Analyst": 2,
        "Engineer": 1,
    }
    assert not any(role["customized"] for role in overview["roles"])


def test_saved_default_applies_to_every_role(staff: TestClient) -> None:
    # given
    staff.put(f"{URL}/default", json=POLICY)

    # when
    overview = staff.get(URL).json()

    # then
    assert overview["default"]["customized"] is True
    assert roles(overview)["Engineer"]["settings"]["tools"] == POLICY["tools"]


def test_role_policy_overrides_default(staff: TestClient) -> None:
    # given
    url = f"{URL}/roles/Analyst"

    # when
    response = staff.put(url, json=POLICY)

    # then
    assert response.status_code == 200
    analyst, engineer = roles(staff.get(URL).json()).values()
    assert analyst["customized"] is True
    assert analyst["settings"]["clearance"] == "CONFIDENTIAL"
    assert analyst["settings"]["budget"]["monthly_tokens"] == 100000
    assert engineer["customized"] is False
    assert engineer["settings"]["clearance"] == "INTERNAL"


async def saved_policy(role: str) -> Policy | None:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        return await session.get(Policy, (org_id, role))


def test_policy_records_who_saved_it_last(staff: TestClient, user: User) -> None:
    # given
    staff.put(f"{URL}/roles/Analyst", json=POLICY)

    # when
    staff.put(f"{URL}/roles/Analyst", json=POLICY | {"injection_threshold": 0.7})

    # then
    policy = asyncio.run(saved_policy("Analyst"))
    assert policy is not None
    assert policy.updated_by_id == user.id


def test_reset_role_follows_default_again(staff: TestClient) -> None:
    # given
    staff.put(f"{URL}/roles/Analyst", json=POLICY)

    # when
    response = staff.delete(f"{URL}/roles/Analyst")

    # then
    assert response.status_code == 204
    assert roles(staff.get(URL).json())["Analyst"]["customized"] is False


def test_unknown_role_is_not_found(staff: TestClient) -> None:
    # when / then
    assert staff.put(f"{URL}/roles/Astronaut", json=POLICY).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_models": ["gpt-9"]},
        {"injection_threshold": 1.5},
        {"above_clearance": "allow"},
        {"clearance": "SECRET"},
        {"tools": {"bank__get_client": "maybe"}},
        {"budget": {"monthly_tokens": -1}},
    ],
)
def test_invalid_policy_is_refused(staff: TestClient, change: dict[str, Any]) -> None:
    # when
    response = staff.put(f"{URL}/roles/Analyst", json=POLICY | change)

    # then
    assert response.status_code == 422
    assert roles(staff.get(URL).json())["Analyst"]["customized"] is False


def test_lists_gateway_tools(staff: TestClient) -> None:
    # given
    app.dependency_overrides[mcp_gateway] = lambda: gateway("bank")

    # when
    try:
        tools = staff.get(f"{URL}/tools").json()
    finally:
        app.dependency_overrides.clear()

    # then
    assert [tool["name"] for tool in tools] == ["bank__get_client", "bank__get_note"]


def test_employees_are_staff_only(staff: TestClient) -> None:
    # when
    listed = staff.get("/api/employees").json()

    # then
    assert listed["total"] == 3
    assert [e["name"] for e in listed["employees"]] == ["Ann Lee", "Bob Ray", "Cy Fox"]


@pytest.mark.parametrize(
    ("query", "names"),
    [
        ("role=Engineer", ["Cy Fox"]),
        ("q=bob", ["Bob Ray"]),
        ("limit=1&offset=1", ["Bob Ray"]),
    ],
)
def test_employees_filter(staff: TestClient, query: str, names: list[str]) -> None:
    # when
    listed = staff.get(f"/api/employees?{query}").json()

    # then
    assert [e["name"] for e in listed["employees"]] == names


def test_me_is_the_signed_in_user(staff: TestClient, user: User) -> None:
    # when
    response = staff.get("/api/employees/me")

    # then
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": f"Bearer {uuid.uuid4().hex}"}]
)
def test_me_without_a_known_user_is_401(headers: dict[str, str]) -> None:
    # given
    client = TestClient(app, headers=headers)

    # when / then
    assert client.get("/api/employees/me").status_code == 401
