"""헬스체크 — 앱이 기동했는지 알리는 최소 신호.

부하테스트와 배포 확인이 본 요청을 보내기 전에 이 응답으로 준비 상태를 판정한다.
"""

from fastapi.testclient import TestClient


def test_헬스체크는_앱이_떠_있으면_UP을_돌려준다(client: TestClient) -> None:
    """헬스체크 — GET /health가 200과 {"status": "UP"}을 돌려준다. 라우터
    등록과 앱 조립이 최소한으로 살아 있다는 확인이다."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP"}
