from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    # given
    url = "/api/health"

    # when
    response = client.get(url)

    # then
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
