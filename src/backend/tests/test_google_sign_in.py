import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app.core import google
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.usefixtures("db")

CLIENT_ID = "test-client.apps.googleusercontent.com"
URL = "/api/auth/google"
GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_set() -> dict[str, Any]:
    public = json.loads(RSAAlgorithm.to_jwk(GOOGLE_KEY.public_key()))
    return {"keys": [{**public, "kid": "key-1", "use": "sig", "alg": "RS256"}]}


@pytest.fixture(autouse=True)
def google_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google sign-in on, with Google's keys served from memory."""
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(google.GOOGLE_KEYS, "keys", {})
    monkeypatch.setattr(google.GOOGLE_KEYS, "fetched", 0.0)

    async def fetch() -> dict[str, jwt.PyJWK]:
        return google.by_id(jwk_set())

    monkeypatch.setattr(google.GOOGLE_KEYS, "fetch", fetch)


def id_token(key: Any = GOOGLE_KEY, **changes: Any) -> str:
    """An ID token as Google signs it, for eve@acme.com."""
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Eve@Acme.com",
        "email_verified": True,
        "name": "Eve Acme",
        "iat": now,
        "exp": now + 600,
    } | changes
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})


def test_new_google_user_starts_an_organization() -> None:
    # when
    response = TestClient(app).post(URL, json={"credential": id_token()})

    # then
    assert response.status_code == 200
    user = response.json()["user"]
    assert (user["email"], user["name"]) == ("eve@acme.com", "Eve Acme")
    assert user["clearance_level"] == "PRIVILEGED"


def test_returning_google_user_signs_in_to_the_same_account() -> None:
    # given
    client = TestClient(app)
    first = client.post(URL, json={"credential": id_token()}).json()

    # when
    again = client.post(URL, json={"credential": id_token()}).json()

    # then
    assert again["user"]["id"] == first["user"]["id"]


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: id_token(OTHER_KEY), id="not signed by Google"),
        pytest.param(lambda: id_token(aud="another-app"), id="another client"),
        pytest.param(lambda: id_token(iss="https://evil.example"), id="issuer"),
        pytest.param(lambda: id_token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(lambda: id_token(email_verified=False), id="unverified"),
        pytest.param(lambda: "not a token", id="garbage"),
    ],
)
def test_token_google_did_not_vouch_for_is_401(token: Any) -> None:
    # given
    request = {"credential": token()}

    # when
    response = TestClient(app).post(URL, json=request)

    # then
    assert response.status_code == 401


def test_google_sign_in_is_off_without_a_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "google_client_id", "")

    # when / then
    response = TestClient(app).post(URL, json={"credential": id_token()})
    assert response.status_code == 404
