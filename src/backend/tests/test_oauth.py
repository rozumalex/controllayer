import base64
import hashlib
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.db.models import User
from app.main import app
from tests.conftest import signed_in
from tests.test_gateway_mcp import ACCEPT, crm  # noqa: F401  (a fixture)

CLAUDE = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
    .decode()
    .rstrip("=")
)
RESOURCE = "http://testserver/api/mcp"


@pytest.fixture
def anonymous(db: None) -> Iterator[TestClient]:
    """A client with no session, as an MCP client starts."""
    with TestClient(app) as client:
        yield client


def register(client: TestClient) -> str:
    metadata = {"client_name": "Claude", "redirect_uris": [CLAUDE]}
    response = client.post("/api/oauth/register", json=metadata)
    assert response.status_code == 201
    return response.json()["client_id"]


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def consent_page(client: TestClient, client_id: str, **extra: str) -> Any:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CLAUDE,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": RESOURCE,
        **extra,
    }
    return client.get("/api/oauth/authorize", params=params, follow_redirects=False)


def approve(client: TestClient, user: User, client_id: str) -> str:
    """Walks the browser through consent, and returns the code."""
    page = consent_page(client, client_id).headers["location"]
    assert page.startswith("/oauth/authorize?")
    request = {**query(page), "explicit": True, "allow": True}
    response = client.post("/api/oauth/consent", json=request, headers=signed_in(user))
    redirect = response.json()["redirect"]
    assert redirect.startswith(CLAUDE)
    assert query(redirect)["state"] == "xyz"
    return query(redirect)["code"]


def trade(client: TestClient, client_id: str, code: str, verifier: str = VERIFIER):
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": CLAUDE,
        "code_verifier": verifier,
        "resource": RESOURCE,
    }
    return client.post("/api/oauth/token", data=form)


def test_mcp_without_a_token_points_to_the_metadata(anonymous: TestClient) -> None:
    # when
    response = anonymous.post("/api/mcp", json={}, headers={"Accept": ACCEPT})

    # then
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="http://testserver'
        '/.well-known/oauth-protected-resource/api/mcp"'
    )


def test_metadata_names_portcullis_as_the_authorization_server(
    anonymous: TestClient,
) -> None:
    # when
    resource = anonymous.get("/.well-known/oauth-protected-resource/api/mcp").json()
    server = anonymous.get("/.well-known/oauth-authorization-server").json()

    # then
    assert resource["resource"] == RESOURCE
    assert resource["authorization_servers"] == ["http://testserver"]
    assert server["issuer"] == "http://testserver"
    assert server["authorization_endpoint"] == "http://testserver/api/oauth/authorize"
    assert server["registration_endpoint"] == "http://testserver/api/oauth/register"
    assert server["code_challenge_methods_supported"] == ["S256"]


def test_registration_makes_a_public_client(anonymous: TestClient) -> None:
    # given
    metadata = {"client_name": "Claude", "redirect_uris": [CLAUDE]}

    # when
    response = anonymous.post("/api/oauth/register", json=metadata)

    # then
    assert response.status_code == 201
    assert response.json()["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in response.json()


def test_unregistered_redirect_uri_is_refused_without_a_redirect(
    anonymous: TestClient,
) -> None:
    # given
    client_id = register(anonymous)

    # when
    response = consent_page(anonymous, client_id, redirect_uri="https://evil.test/cb")

    # then
    assert response.status_code == 400
    assert "location" not in response.headers


def test_wrong_pkce_verifier_is_refused(anonymous: TestClient, user: User) -> None:
    # given
    client_id = register(anonymous)
    code = approve(anonymous, user, client_id)

    # when
    response = trade(anonymous, client_id, code, verifier="w" * 64)

    # then
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_code_works_once(anonymous: TestClient, user: User) -> None:
    # given
    client_id = register(anonymous)
    code = approve(anonymous, user, client_id)
    assert trade(anonymous, client_id, code).status_code == 200

    # when
    response = trade(anonymous, client_id, code)

    # then
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_token_for_another_resource_is_refused(
    anonymous: TestClient, user: User
) -> None:
    # given
    client_id = register(anonymous)
    page = consent_page(anonymous, client_id, resource="https://other.test/mcp")
    request = {**query(page.headers["location"]), "allow": True}

    # when
    response = anonymous.post(
        "/api/oauth/consent", json=request, headers=signed_in(user)
    )

    # then
    assert query(response.json()["redirect"])["error"] == "invalid_target"


@pytest.mark.usefixtures("crm")
def test_token_lists_only_the_tools_of_the_users_role(
    anonymous: TestClient, user: User
) -> None:
    # given
    client_id = register(anonymous)
    code = approve(anonymous, user, client_id)
    token = trade(anonymous, client_id, code).json()["access_token"]
    headers = {"Accept": ACCEPT, "Authorization": f"Bearer {token}"}
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    # when
    response = anonymous.post("/api/mcp", json=request, headers=headers)

    # then
    tools = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert tools == {"crm__get_client"}
