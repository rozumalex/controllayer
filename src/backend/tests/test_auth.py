import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models import User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id, signed_in

ADMIN_URLS = [
    ("GET", "/api/traces"),
    ("GET", "/api/mcp-servers"),
    ("POST", f"/api/mcp-servers/{uuid.uuid4()}/approve"),
    ("PUT", "/api/demo/fx-rates"),
    ("GET", "/api/policy"),
    ("PUT", "/api/policy/default"),
    ("GET", "/api/employees"),
    ("GET", "/api/identity-provider"),
    ("PUT", "/api/identity-provider"),
]


async def staff(clearance: str | None) -> User:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            name="Staff",
            clearance_level=clearance,
            org_id=org_id,
        )
        session.add(user)
        await session.commit()
        return user


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", "/api/v1/chat/completions"),
        ("GET", "/api/v1/models"),
        *ADMIN_URLS,
    ],
)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": f"Bearer {uuid.uuid4().hex}"}]
)
def test_without_a_known_user_is_401(
    method: str, url: str, headers: dict[str, str]
) -> None:
    # given
    client = TestClient(app, headers=headers)

    # when / then
    assert client.request(method, url, json={}).status_code == 401


def test_health_needs_no_user() -> None:
    # given
    client = TestClient(app)

    # when / then
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize(("method", "url"), ADMIN_URLS)
@pytest.mark.parametrize("clearance", [None, "LOW", "STANDARD"])
def test_admin_needs_a_privileged_user(
    method: str, url: str, clearance: str | None
) -> None:
    # given
    user = asyncio.run(staff(clearance))
    client = TestClient(app, headers=signed_in(user))

    # when / then
    assert client.request(method, url, json={}).status_code == 403
