import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import deps
from app.core.schema.policy import ToolAction
from app.db.models import ControlEvent, McpServer, User
from app.db.policy import DEFAULT_ROLE
from app.db.session import SessionLocal
from app.main import app
from tests.conftest import demo_org_id, signed_in
from tests.test_policy_enforcement import add_analyst, calls, connect, policy, save

URL = "/api/mcp"
ACCEPT = "application/json, text/event-stream"


async def add_crm() -> None:
    org_id = await demo_org_id()
    async with SessionLocal() as session:
        session.add(McpServer(org_id=org_id, name="crm", url="http://crm.test/mcp"))
        await session.commit()


@pytest.fixture
def crm(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo organization's crm server: everyone may call get_client, and
    only the analyst may call delete_client."""
    monkeypatch.setattr(deps, "mcp_connect", lambda: connect)
    asyncio.run(add_crm())
    blocked = {"crm__delete_client": ToolAction.BLOCK}
    asyncio.run(save(DEFAULT_ROLE, policy(tools=blocked)))
    asyncio.run(save("Analyst", policy(tools={})))


def rpc(client: TestClient, method: str, **params: Any) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = client.post(URL, json=request, headers={"Accept": ACCEPT})
    assert response.status_code == 200
    return response.json()["result"]


def tool_names(client: TestClient) -> set[str]:
    return {tool["name"] for tool in rpc(client, "tools/list")["tools"]}


@pytest.fixture
def analyst(crm: None) -> Iterator[TestClient]:
    user = asyncio.run(add_analyst())
    with TestClient(app, headers=signed_in(user)) as client:
        yield client


@pytest.fixture
def tester(crm: None, user: User) -> Iterator[TestClient]:
    with TestClient(app, headers=signed_in(user)) as client:
        yield client


def test_lists_only_the_tools_the_role_allows(
    tester: TestClient, analyst: TestClient
) -> None:
    # when
    tester_tools = tool_names(tester)
    analyst_tools = tool_names(analyst)

    # then
    assert tester_tools == {"crm__get_client"}
    assert analyst_tools == {"crm__get_client", "crm__delete_client"}


def test_call_to_a_blocked_tool_is_refused(tester: TestClient) -> None:
    # given
    calls.clear()
    arguments = {"client_id": "C1"}

    # when
    result = rpc(tester, "tools/call", name="crm__delete_client", arguments=arguments)

    # then
    assert result["isError"] is True
    assert "blocked" in result["content"][0]["text"]
    assert calls == []


async def tool_events(user: User) -> list[ControlEvent]:
    async with SessionLocal() as session:
        query = select(ControlEvent).where(ControlEvent.event == "request")
        events = await session.scalars(query.where(ControlEvent.user_id == user.id))
        return list(events)


def test_call_is_recorded_under_the_user(
    tester: TestClient, user: User, no_events: None
) -> None:
    # given
    arguments = {"client_id": "C1"}

    # when
    result = rpc(tester, "tools/call", name="crm__get_client", arguments=arguments)

    # then
    assert result["isError"] is False
    [event] = asyncio.run(tool_events(user))
    assert event.data["tool"] == "get_client"
    assert event.data["agent_id"] == "mcp-client"


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic abc"])
def test_needs_a_session_token(db: None, header: str | None) -> None:
    # given
    headers = {"Authorization": header} if header else {}

    # when
    with TestClient(app) as client:
        response = client.post(URL, headers=headers, json={})

    # then
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer resource_metadata=")
