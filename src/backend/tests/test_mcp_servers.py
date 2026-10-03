from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import mcp_types as types
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app.api.deps import mcp_connect
from app.control.adapters.mcp_gateway import McpGateway, UpstreamServer
from app.main import app
from tests.test_mcp_gateway import bank

URL = "/api/mcp-servers"
BANK = {"name": "bank", "url": "http://bank-mcp:5000/mcp", "auth_header": "Bearer x"}


@asynccontextmanager
async def connect(server: UpstreamServer) -> AsyncIterator[Client]:
    if "unreachable" in server.url:
        raise ConnectionError("connection refused")
    async with Client(bank) as client:
        yield client


@pytest.fixture
def api(db: None) -> Iterator[TestClient]:
    app.dependency_overrides[mcp_connect] = lambda: connect
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_server_hides_auth_header(api: TestClient) -> None:
    # when
    response = api.post(URL, json=BANK)

    # then
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "bank"
    assert data["enabled"] is True
    assert data["has_auth"] is True
    assert "Bearer x" not in response.text


def test_unreachable_server_is_refused(api: TestClient) -> None:
    # given
    server = {**BANK, "url": "http://unreachable:5000/mcp"}

    # when
    response = api.post(URL, json=server)

    # then
    assert response.status_code == 422
    assert api.get(URL).json() == []


def test_duplicate_name_is_refused(api: TestClient) -> None:
    # given
    api.post(URL, json=BANK)

    # when / then
    assert api.post(URL, json=BANK).status_code == 409


def test_name_with_underscores_is_refused(api: TestClient) -> None:
    # given
    server = {**BANK, "name": "my__bank"}

    # when / then
    assert api.post(URL, json=server).status_code == 422


def test_disable_list_tools_and_delete(api: TestClient) -> None:
    # given
    id = api.post(URL, json=BANK).json()["id"]

    # when
    disabled = api.patch(f"{URL}/{id}", json={"enabled": False})
    tools = api.get(f"{URL}/{id}/tools")
    deleted = api.delete(f"{URL}/{id}")

    # then
    assert disabled.json()["enabled"] is False
    assert {tool["name"] for tool in tools.json()} == {"get_client", "get_note"}
    assert deleted.status_code == 204
    assert api.get(URL).json() == []


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def test_gateway_serves_mcp_over_http(db: None) -> None:
    # given
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = MCP_HEADERS

    # when
    with TestClient(app) as client:
        response = client.post("/api/mcp", json=request, headers=headers)

    # then
    assert response.status_code == 200
    assert response.json()["result"]["tools"] == []


def test_gateway_reads_agent_id_header(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    async def call_tool(self, name, arguments, agent_id) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=agent_id)]
        )

    monkeypatch.setattr(McpGateway, "call_tool", call_tool)
    params = {"name": "bank__get_client", "arguments": {}}
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    headers = {**MCP_HEADERS, "X-Agent-Id": "judge-low"}

    # when
    with TestClient(app) as client:
        response = client.post("/api/mcp", json=request, headers=headers)

    # then
    assert response.json()["result"]["content"][0]["text"] == "judge-low"
