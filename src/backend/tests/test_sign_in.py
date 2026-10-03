import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import PRIVILEGED
from app.core.config import settings
from app.core.passwords import hash_password
from app.db.models import Organization, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id

pytestmark = pytest.mark.usefixtures("db")

SIGN_UP = {
    "organization": "Acme Bank",
    "name": "Eve Admin",
    "email": "Eve@Acme.com",
    "password": "correct horse battery",
}


def bearer(signed: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {signed['token']}"}


async def stored_user(email: str) -> User | None:
    async with SessionLocal() as session:
        return await session.scalar(select(User).where(User.email == email))


async def organization_of(user: User) -> Organization | None:
    async with SessionLocal() as session:
        return await session.get(Organization, user.org_id)


async def add_demo_account() -> None:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        session.add(
            User(
                email=settings.demo_email,
                name="Demo User",
                title="Vice President",
                clearance_level=PRIVILEGED,
                org_id=org_id,
                password_hash=await hash_password(settings.demo_password),
            )
        )
        await session.commit()


def test_sign_up_starts_an_organization_with_its_admin() -> None:
    # given
    client = TestClient(app)

    # when
    signed = client.post("/api/auth/sign-up", json=SIGN_UP)

    # then
    assert signed.status_code == 201
    user = asyncio.run(stored_user("eve@acme.com"))
    assert user is not None
    org = asyncio.run(organization_of(user))
    assert org is not None and org.name == "Acme Bank"
    assert org.slug.startswith("acme-bank-")
    # The new admin opens the admin pages of their empty organization.
    policy = client.get("/api/policy", headers=bearer(signed.json()))
    assert policy.status_code == 200
    assert policy.json()["roles"] == []


def test_password_is_stored_hashed() -> None:
    # given
    TestClient(app).post("/api/auth/sign-up", json=SIGN_UP)

    # when
    user = asyncio.run(stored_user("eve@acme.com"))

    # then
    assert user is not None and user.password_hash is not None
    assert SIGN_UP["password"] not in user.password_hash
    assert user.password_hash.startswith("scrypt$")


def test_sign_up_with_a_taken_email_is_409() -> None:
    # given
    client = TestClient(app)
    client.post("/api/auth/sign-up", json=SIGN_UP)

    # when / then
    assert client.post("/api/auth/sign-up", json=SIGN_UP).status_code == 409


def test_short_password_is_refused() -> None:
    # given
    request = {**SIGN_UP, "password": "short"}

    # when / then
    assert TestClient(app).post("/api/auth/sign-up", json=request).status_code == 422


def test_sign_in_with_the_right_password() -> None:
    # given
    client = TestClient(app)
    client.post("/api/auth/sign-up", json=SIGN_UP)
    request = {"email": "eve@acme.com", "password": SIGN_UP["password"]}

    # when
    signed = client.post("/api/auth/sign-in", json=request).json()

    # then
    me = client.get("/api/employees/me", headers=bearer(signed)).json()
    assert me["email"] == "eve@acme.com"


@pytest.mark.parametrize(
    "request_body",
    [
        {"email": "eve@acme.com", "password": "wrong password"},
        {"email": "nobody@acme.com", "password": "correct horse battery"},
    ],
)
def test_wrong_email_or_password_is_401(request_body: dict[str, str]) -> None:
    # given
    client = TestClient(app)
    client.post("/api/auth/sign-up", json=SIGN_UP)

    # when
    response = client.post("/api/auth/sign-in", json=request_body)

    # then
    # The same answer either way, so it doesn't tell which emails exist.
    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong email or password"


def test_demo_lands_in_the_demo_organization() -> None:
    # given
    asyncio.run(add_demo_account())
    client = TestClient(app)

    # when
    signed = client.post("/api/auth/demo").json()

    # then
    me = client.get("/api/employees/me", headers=bearer(signed)).json()
    assert me["email"] == settings.demo_email
    assert me["role"] == "Vice President"


def test_demo_account_signs_in_with_its_password() -> None:
    # given
    asyncio.run(add_demo_account())
    request = {"email": settings.demo_email, "password": settings.demo_password}

    # when / then
    response = TestClient(app).post("/api/auth/sign-in", json=request)
    assert response.status_code == 200


def test_sign_out_ends_the_session() -> None:
    # given
    client = TestClient(app)
    headers = bearer(client.post("/api/auth/sign-up", json=SIGN_UP).json())

    # when
    client.post("/api/auth/sign-out", headers=headers)

    # then
    assert client.get("/api/employees/me", headers=headers).status_code == 401
