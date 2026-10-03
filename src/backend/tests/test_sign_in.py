import asyncio
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import PRIVILEGED
from app.api.endpoints import auth
from app.core.config import settings
from app.core.mail import MailError
from app.db.models import EmailCode, Organization, User
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id

pytestmark = pytest.mark.usefixtures("db")

EVE = "Eve.Adams@Acme.com"


@pytest.fixture
def inbox(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """The emails sign-in sends, kept instead of sent."""
    sent: list[dict[str, str]] = []

    async def send_mail(to: str, subject: str, text: str) -> None:
        sent.append({"to": to, "subject": subject, "text": text})

    monkeypatch.setattr(settings, "smtp_host", "mailpit")
    monkeypatch.setattr(auth, "send_mail", send_mail)
    return sent


def code_in(mail: dict[str, str]) -> str:
    found = re.search(r"\b\d{6}\b", mail["text"])
    assert found
    return found.group()


def sign_in(client: TestClient, inbox: list[dict[str, str]], email: str) -> Any:
    client.post("/api/auth/email", json={"email": email})
    code = code_in(inbox[-1])
    return client.post("/api/auth/email/verify", json={"email": email, "code": code})


async def stored(email: str) -> tuple[User | None, Organization | None]:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
        org = await session.get(Organization, user.org_id) if user else None
        return user, org


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
            )
        )
        await session.commit()


def test_code_goes_to_the_email(inbox: list[dict[str, str]]) -> None:
    # when
    response = TestClient(app).post("/api/auth/email", json={"email": EVE})

    # then
    assert response.json() == {"sent": True}
    [mail] = inbox
    assert mail["to"] == "eve.adams@acme.com"
    assert code_in(mail) in mail["subject"]


def test_code_is_stored_hashed(inbox: list[dict[str, str]]) -> None:
    # given
    TestClient(app).post("/api/auth/email", json={"email": EVE})

    # when
    row = asyncio.run(code_row("eve.adams@acme.com"))

    # then
    assert row is not None
    assert code_in(inbox[0]) not in row.code_hash


async def code_row(email: str) -> EmailCode | None:
    async with SessionLocal() as session:
        return await session.get(EmailCode, email)


def test_first_sign_in_starts_an_organization(inbox: list[dict[str, str]]) -> None:
    # when
    response = sign_in(TestClient(app), inbox, EVE)

    # then
    assert response.status_code == 200
    user, org = asyncio.run(stored("eve.adams@acme.com"))
    assert user is not None and user.name == "Eve Adams"
    assert user.clearance_level == PRIVILEGED
    assert org is not None and org.name == "acme.com"


def test_public_mail_user_gets_an_organization_of_their_own(
    inbox: list[dict[str, str]],
) -> None:
    # when
    sign_in(TestClient(app), inbox, "eve@gmail.com")

    # then
    _, org = asyncio.run(stored("eve@gmail.com"))
    assert org is not None and org.name == "Eve's organization"


def test_returning_user_signs_in_to_the_same_account(
    inbox: list[dict[str, str]],
) -> None:
    # given
    client = TestClient(app)
    first = sign_in(client, inbox, EVE).json()

    # when
    again = sign_in(client, inbox, EVE).json()

    # then
    assert again["user"]["id"] == first["user"]["id"]


def test_wrong_code_is_401(inbox: list[dict[str, str]]) -> None:
    # given
    client = TestClient(app)
    client.post("/api/auth/email", json={"email": EVE})
    wrong = f"{(int(code_in(inbox[0])) + 1) % 10**6:06d}"

    # when
    response = client.post("/api/auth/email/verify", json={"email": EVE, "code": wrong})

    # then
    assert response.status_code == 401


def test_code_works_once(inbox: list[dict[str, str]]) -> None:
    # given
    client = TestClient(app)
    client.post("/api/auth/email", json={"email": EVE})
    request = {"email": EVE, "code": code_in(inbox[0])}
    client.post("/api/auth/email/verify", json=request)

    # when / then
    assert client.post("/api/auth/email/verify", json=request).status_code == 401


def test_too_many_wrong_codes_void_the_code(
    inbox: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "email_code_attempts", 2)
    client = TestClient(app)
    client.post("/api/auth/email", json={"email": EVE})
    code = code_in(inbox[0])
    wrong = f"{(int(code) + 1) % 10**6:06d}"
    for _ in range(2):
        client.post("/api/auth/email/verify", json={"email": EVE, "code": wrong})

    # when
    response = client.post("/api/auth/email/verify", json={"email": EVE, "code": code})

    # then
    assert response.status_code == 401


def test_new_code_waits_a_moment(inbox: list[dict[str, str]]) -> None:
    # given
    client = TestClient(app)
    client.post("/api/auth/email", json={"email": EVE})

    # when
    response = client.post("/api/auth/email", json={"email": EVE})

    # then
    assert response.status_code == 429
    assert len(inbox) == 1


def test_mail_failure_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    async def send_mail(to: str, subject: str, text: str) -> None:
        raise MailError("refused")

    monkeypatch.setattr(settings, "smtp_host", "mailpit")
    monkeypatch.setattr(auth, "send_mail", send_mail)

    # when / then
    response = TestClient(app).post("/api/auth/email", json={"email": EVE})
    assert response.status_code == 503


def test_email_sign_in_is_off_without_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "smtp_host", "")

    # when / then
    response = TestClient(app).post("/api/auth/email", json={"email": EVE})
    assert response.status_code == 503


@pytest.mark.parametrize("path", ["/api/auth/demo", "/api/auth/email"])
def test_demo_lands_in_the_demo_organization(path: str) -> None:
    # given
    asyncio.run(add_demo_account())
    client = TestClient(app)

    # when
    signed = client.post(path, json={"email": settings.demo_email}).json()

    # then
    headers = {"Authorization": f"Bearer {signed['token']}"}
    me = client.get("/api/employees/me", headers=headers).json()
    assert me["email"] == settings.demo_email
    assert me["role"] == "Vice President"


def test_sign_out_ends_the_session(inbox: list[dict[str, str]]) -> None:
    # given
    client = TestClient(app)
    token = sign_in(client, inbox, EVE).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # when
    client.post("/api/auth/sign-out", headers=headers)

    # then
    assert client.get("/api/employees/me", headers=headers).status_code == 401
