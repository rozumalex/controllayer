import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.server.mcpserver import MCPServer

from app.api.deps import control_layer, mcp_connect
from app.control.adapters.mcp_gateway import McpGateway, UpstreamServer
from app.control.envelope import Direction, Envelope
from app.control.guards.prompt_injection import PromptInjectionGuard
from app.db.models import User
from app.main import app
from app.servers.bank import bank
from app.servers.fx import POISONED, fx, poison
from tests.conftest import signed_in
from tests.test_mcp_gateway import ListSink, Upstream, text

SERVERS = {"fx-rates": fx, "bank": bank}
TOOL = "fx-rates__get_fx_rate"


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    yield
    poison(False)


@asynccontextmanager
async def connect(server: UpstreamServer) -> AsyncIterator[Client]:
    upstream: MCPServer = SERVERS[server.name]
    async with Client(upstream) as client:
        yield client


def gateway(
    server: Upstream, sink: ListSink | None = None, pinned: list[Any] | None = None
) -> McpGateway:
    async def servers() -> list[Upstream]:
        return [server]

    async def pin(_: UpstreamServer, pins: dict[str, str]) -> None:
        if pinned is not None:
            pinned.append(pins)

    return McpGateway(control_layer(sink), connect, servers, pin=pin)


def names(subject: McpGateway) -> set[str]:
    return {tool.name for tool in asyncio.run(subject.list_tools())}


def test_regex_catches_the_poisoned_description() -> None:
    # given
    envelope = Envelope(Direction.DEFINITION, "a", "fx", "t", {"d": POISONED})

    # when
    verdict = asyncio.run(PromptInjectionGuard().inspect(envelope))

    # then
    assert verdict.action == "block"
    assert verdict.reason == "matched: concealment, instruction_tag"


def test_clean_tool_is_listed_and_pinned() -> None:
    # given
    pinned: list[Any] = []
    subject = gateway(Upstream("fx-rates"), pinned=pinned)

    # when
    tools = names(subject)

    # then
    assert tools == {TOOL}
    assert list(pinned[0]) == ["get_fx_rate"]


def test_poisoned_tool_is_hidden_refused_and_traced() -> None:
    # given
    sink = ListSink()
    pinned: list[Any] = []
    subject = gateway(Upstream("fx-rates"), sink, pinned)
    poison(True)

    # when
    tools = names(subject)

    # then
    assert tools == set()
    assert pinned == []
    result = asyncio.run(subject.call_tool(TOOL, {"base": "EUR"}, "a"))
    assert result.is_error is True
    assert "blocked" in text(result)
    verdict = next(e for e in sink.events if e["guard"] == "tool_poisoning")
    assert verdict["action"] == "block"
    assert verdict["reason"].startswith("prompt_injection: matched:")
    assert "IMPORTANT" not in str(sink.events)


def test_changed_definition_is_hidden() -> None:
    # given
    sink = ListSink()
    stale = Upstream("fx-rates", tool_pins={"get_fx_rate": "0" * 64})
    subject = gateway(stale, sink)

    # when
    tools = names(subject)

    # then
    assert tools == set()
    verdict = next(e for e in sink.events if e["guard"] == "tool_poisoning")
    assert verdict["reason"] == "definition changed since it was approved"


def test_bank_tools_pass() -> None:
    # given
    sink = ListSink()
    subject = gateway(Upstream("bank"), sink)

    # when
    tools = names(subject)

    # then
    assert len(tools) == len(asyncio.run(bank.list_tools()))
    assert sink.events == []


@pytest.fixture
def api(db: None, user: User) -> Iterator[TestClient]:
    app.dependency_overrides[mcp_connect] = lambda: connect
    yield TestClient(app, headers=signed_in(user))
    app.dependency_overrides.clear()


def test_changed_tool_is_flagged_until_approved(api: TestClient) -> None:
    # given
    url = "/api/mcp-servers"
    id = api.post(url, json={"name": "fx-rates", "url": "http://fx.test/mcp"})
    tools = f"{url}/{id.json()['id']}/tools"
    api.put("/api/demo/fx-rates", json={"poisoned": True})
    changed = api.get(tools).json()[0]["changed"]

    # when
    response = api.post(f"{url}/{id.json()['id']}/approve")

    # then
    assert response.status_code == 200
    assert changed is True
    assert api.get(tools).json()[0]["changed"] is False
