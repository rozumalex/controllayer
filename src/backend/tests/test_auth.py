import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", "/api/chat"),
        ("POST", "/api/chat/stream"),
        ("GET", "/api/traces"),
        ("GET", "/api/mcp-servers"),
        ("GET", "/api/policy"),
        ("PUT", "/api/policy/default"),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"User-Id": str(uuid.uuid4())}])
def test_without_a_known_user_is_401(
    method: str, url: str, headers: dict[str, str]
) -> None:
    # given
    client = TestClient(app, headers=headers)

    # when / then
    assert client.request(method, url, json={}).status_code == 401


@pytest.mark.parametrize("url", ["/api/health", "/api/employees"])
def test_sign_in_needs_no_user(url: str) -> None:
    # given
    client = TestClient(app)

    # when / then
    assert client.get(url).status_code == 200
