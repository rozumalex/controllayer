import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.endpoints.auth import user_for
from app.core.config import settings
from app.db.models import (
    BankAccount,
    BankClient,
    BankTrade,
    DirectoryGroup,
    McpServer,
    Organization,
    User,
    group_members,
)
from app.db.sandbox import fill_pool, key_hash
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id
from tests.test_bank_mcp import TRADER, seed
from tests.test_sign_in import add_demo_account

pytestmark = pytest.mark.usefixtures("db")

KEY = "a" * 64
BANK_URL = "http://localhost:8000/api/bank/mcp"
NEWS_URL = "https://news.example.com/mcp"


async def add_directory() -> None:
    """A group with the trader in it, and two MCP servers: the bank's and
    another."""
    org_id = await demo_org_id()
    async with SessionLocal.begin() as session:
        trader = await session.scalar(select(User).where(User.email == TRADER))
        assert trader is not None
        session.add(DirectoryGroup(org_id=org_id, display_name="traders"))
        session.add(McpServer(org_id=org_id, name="bank", url=BANK_URL))
        session.add(McpServer(org_id=org_id, name="news", url=NEWS_URL))
        await session.flush()
        group = await session.scalar(select(DirectoryGroup.id))
        await session.execute(
            group_members.insert().values(group_id=group, user_id=trader.id)
        )


@pytest.fixture
def demo() -> None:
    """The demo organization, with its bank, demo account and directory."""
    asyncio.run(seed())
    asyncio.run(add_demo_account())
    asyncio.run(add_directory())


def sign_in(key: str = KEY) -> Any:
    return TestClient(app).post("/api/auth/demo", json={"key": key})


async def sandbox_id(key: str = KEY) -> uuid.UUID:
    async with SessionLocal() as session:
        org_id = await session.scalar(
            select(Organization.id).where(
                Organization.sandbox_key_hash == key_hash(key)
            )
        )
        assert org_id is not None
        return org_id


async def count(model: Any, org_id: uuid.UUID) -> int:
    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.count()).select_from(model).where(model.org_id == org_id)
        )
        return total or 0


async def staff_member(org_id: uuid.UUID, email: str) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.org_id == org_id, User.email == email)
        )
        assert user is not None
        return user


def test_first_sign_in_copies_the_demo_organization(demo: None) -> None:
    # given
    demo_id = asyncio.run(demo_org_id())

    # when
    response = sign_in()

    # then
    assert response.status_code == 200
    org_id = asyncio.run(sandbox_id())
    for model in (User, BankClient, BankAccount, BankTrade):
        copies = asyncio.run(count(model, org_id))
        assert copies == asyncio.run(count(model, demo_id)) > 0


def test_copies_refer_to_the_copied_staff(demo: None) -> None:
    # when
    sign_in()

    # then
    org_id = asyncio.run(sandbox_id())
    trader = asyncio.run(staff_member(org_id, TRADER))
    original = asyncio.run(staff_member(asyncio.run(demo_org_id()), TRADER))
    assert trader.id != original.id

    async def references() -> tuple[Any, Any]:
        async with SessionLocal() as session:
            rm = await session.scalar(
                select(BankClient.primary_rm_id).where(BankClient.org_id == org_id)
            )
            member = await session.scalar(
                select(group_members.c.user_id)
                .join(DirectoryGroup)
                .where(DirectoryGroup.org_id == org_id)
            )
            return rm, member

    assert asyncio.run(references()) == (trader.id, trader.id)


def test_sandbox_bank_server_serves_its_own_copy(demo: None) -> None:
    # when
    sign_in()

    # then
    org_id = asyncio.run(sandbox_id())

    async def urls() -> dict[str, str]:
        async with SessionLocal() as session:
            rows = await session.execute(
                select(McpServer.name, McpServer.url).where(McpServer.org_id == org_id)
            )
            return dict(rows.all())

    assert asyncio.run(urls()) == {
        "bank": f"{BANK_URL}?org={org_id}",
        "news": NEWS_URL,
    }


def test_same_key_signs_in_to_the_same_sandbox(demo: None) -> None:
    # given
    first = sign_in().json()

    # when
    again = sign_in().json()

    # then
    assert again["user"]["id"] == first["user"]["id"]


def test_each_key_gets_a_sandbox_of_its_own(demo: None) -> None:
    # given
    first = sign_in().json()

    # when
    other = sign_in("b" * 64).json()

    # then
    assert other["user"]["id"] != first["user"]["id"]


def test_short_key_is_refused() -> None:
    # when / then
    assert sign_in("short").status_code == 422


def test_demo_needs_the_seed() -> None:
    # when / then
    assert sign_in().status_code == 404


def tool_call(org: str, tool: str, **arguments: Any) -> Any:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    headers = {
        "Authorization": "Bearer bank-secret",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app) as client:
        return client.post(f"/api/bank/mcp?org={org}", headers=headers, json=request)


def test_bank_tool_changes_only_the_sandbox_copy(
    demo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "bank_mcp_token", "bank-secret")
    sign_in()
    org_id = asyncio.run(sandbox_id())

    # when
    response = tool_call(
        str(org_id),
        "restrict_account",
        account_id="ACC-0000001",
        restriction="RISK_REVIEW",
    )

    # then
    assert response.status_code == 200
    assert response.json()["result"].get("isError") is not True

    async def statuses() -> dict[uuid.UUID, str]:
        async with SessionLocal() as session:
            rows = await session.execute(
                select(BankAccount.org_id, BankAccount.status).where(
                    BankAccount.account_id == "ACC-0000001"
                )
            )
            return {org: status for org, status in rows.all()}

    demo_id = asyncio.run(demo_org_id())
    assert asyncio.run(statuses()) == {org_id: "RESTRICTED", demo_id: "OPEN"}


def test_bank_refuses_an_org_that_is_not_a_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "bank_mcp_token", "bank-secret")

    # when / then
    assert tool_call("nope", "get_client", client_id="CLT-000001").status_code == 400


def test_email_sign_in_finds_the_user_outside_the_sandboxes(demo: None) -> None:
    # given
    sign_in()

    # when
    async def signed_in_org() -> uuid.UUID | None:
        async with SessionLocal() as session:
            return (await user_for(session, TRADER, None)).org_id

    # then
    assert asyncio.run(signed_in_org()) == asyncio.run(demo_org_id())


async def spare() -> int:
    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.count()).where(
                Organization.sandbox, Organization.sandbox_key_hash.is_(None)
            )
        )
        return total or 0


def test_fill_pool_copies_until_the_pool_is_full(
    demo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "demo_sandbox_pool", 2)

    # when
    asyncio.run(fill_pool())

    # then
    assert asyncio.run(spare()) == 2


def test_first_sign_in_claims_a_sandbox_from_the_pool(
    demo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "demo_sandbox_pool", 1)
    asyncio.run(fill_pool())

    async def pooled() -> uuid.UUID | None:
        async with SessionLocal() as session:
            return await session.scalar(
                select(Organization.id).where(Organization.sandbox)
            )

    waiting = asyncio.run(pooled())

    # when
    response = sign_in()

    # then
    assert response.status_code == 200
    assert asyncio.run(sandbox_id()) == waiting
    # The copy that takes its place, made after the answer.
    assert asyncio.run(spare()) == 1
