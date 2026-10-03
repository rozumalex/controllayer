import tomllib
from pathlib import Path

from fastapi.testclient import TestClient


def test_swagger_ui(client: TestClient) -> None:
    # given
    url = "/api/docs"

    # when
    response = client.get(url)

    # then
    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_redoc(client: TestClient) -> None:
    # given
    url = "/api/redoc"

    # when / then
    assert client.get(url).status_code == 200


def test_openapi_schema(client: TestClient) -> None:
    # given
    url = "/api/openapi.json"

    # when
    response = client.get(url)

    # then
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_info_matches_pyproject(client: TestClient) -> None:
    # given
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text())["project"]

    # when
    info = client.get("/api/openapi.json").json()["info"]

    # then
    assert info["title"] == project["name"]
    assert info["description"] == project["description"]
    assert info["version"] == project["version"]
