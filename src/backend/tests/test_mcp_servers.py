from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app.api.deps import mcp_connect
from app.control.adapters.mcp_gateway import UpstreamServer
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
    assert {t["name"]: t["read_only"] for t in tools.json()} == {
        "get_client": True,
        "get_note": None,
    }
    assert deleted.status_code == 204
    assert api.get(URL).json() == []
