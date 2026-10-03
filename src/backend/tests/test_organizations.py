import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.event_sink import DatabaseEventSink
from app.db.models import McpServer, Organization, User
from app.db.session import SessionLocal

pytestmark = pytest.mark.usefixtures("db", "no_events")


async def other_org() -> dict[str, Any]:
    """Another organization, with an employee and an MCP server of its own."""
    async with SessionLocal() as session:
        org = Organization(slug="acme", name="Acme")
        session.add(org)
        await session.flush()
        staff = User(email="eve@acme.com", name="Eve Acme", title="Analyst")
        server = McpServer(name="crm", url="http://crm.acme.test/mcp")
        staff.org_id = server.org_id = org.id
        session.add_all([staff, server])
        await session.commit()
        return {"org_id": org.id, "user_id": staff.id, "server_id": server.id}


def test_mcp_server_of_another_organization_is_hidden(client: TestClient) -> None:
    # given
    other = asyncio.run(other_org())

    # when
    listed = client.get("/api/mcp-servers").json()
    tools = client.get(f"/api/mcp-servers/{other['server_id']}/tools")

    # then
    assert listed == []
    assert tools.status_code == 404


def test_employees_of_another_organization_are_hidden(client: TestClient) -> None:
    # given
    asyncio.run(other_org())

    # when
    employees = client.get("/api/employees").json()["employees"]
    sign_in = client.get("/api/employees/sign-in").json()

    # then
    assert "Eve Acme" not in {e["name"] for e in employees}
    assert "Eve Acme" not in {e["name"] for e in sign_in}


def test_trace_of_another_organization_is_hidden(client: TestClient) -> None:
    # given
    other = asyncio.run(other_org())
    trace_id = uuid.uuid4().hex
    event = {
        "event": "request",
        "trace_id": trace_id,
        "user_id": str(other["user_id"]),
        "org_id": str(other["org_id"]),
    }
    asyncio.run(DatabaseEventSink().write(event))

    # when
    listed = client.get("/api/traces").json()
    detail = client.get(f"/api/traces/{trace_id}")

    # then
    assert listed["traces"] == []
    assert listed["stats"]["requests"] == 0
    assert detail.status_code == 404
