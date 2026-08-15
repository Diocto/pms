from fastapi.testclient import TestClient


def test_헬스체크는_앱이_떠_있으면_UP을_돌려준다(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}
