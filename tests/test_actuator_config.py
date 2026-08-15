"""`GET /api/internal/config` (테스트 T87~T89d, 스펙 D26).

F04의 락 On/Off 대조는 실행 전에 스위치가 실제로 꺼졌는지 확인해야 한다.
확인 없이 돌리면 두 회차가 같은 조건이 되어도 결과가 "차이 없음"으로 나오고,
그것이 "락이 없어도 되더라"라는 정반대 결론으로 읽힌다.

**값과 구현을 함께 본다** — 값은 "무엇을 의도했는가", 주입된 클래스는
"실제로 무엇이 들어갔는가"다. 컨테이너 배선 실수 하나면 둘이 갈라진다.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _config_response(monkeypatch, **environment) -> dict:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/internal/config")
    assert response.status_code == 200
    return response.json()


def test_T87_라우트가_실제로_등록되고_필수_키가_있다(monkeypatch):
    body = _config_response(monkeypatch)
    # 필수는 PMS_LOCK_ENABLED 하나다 (D26)
    assert "PMS_LOCK_ENABLED" in body["loadTest"]


def test_T88_키는_조작자가_치는_환경변수_이름_그대로의_평평한_문자열이다(monkeypatch):
    body = _config_response(monkeypatch)
    load_test = body["loadTest"]
    # F01 소유 키 6개 전부, 중첩 없이
    assert set(load_test) >= {
        "PMS_LOCK_ENABLED",
        "PMS_LOCK_WAIT_MILLIS",
        "PMS_LOCK_TTL_SECONDS",
        "PMS_RESERVATION_HOLD_MINUTES",
        "PMS_RESERVATION_EXPIRE_SCAN_SECONDS",
        "PMS_PAYMENT_DECLINE_RATE",
    }
    assert all(not isinstance(value, dict) for value in load_test.values())
    # 바깥 키는 camelCase 규칙 그대로다 — 예외는 안쪽 키뿐이다
    assert "loadTest" in body and "implementations" in body


def test_T89_false로_기동하면_값과_구현이_함께_꺼진다(monkeypatch):
    body = _config_response(monkeypatch, PMS_LOCK_ENABLED="false")
    assert body["loadTest"]["PMS_LOCK_ENABLED"] is False
    # T89b — 값만 false가 아니라 컨테이너가 실제로 NoOp을 물고 있다
    assert body["implementations"]["LockPort"] == "NoOpLockAdapter"


def test_T89_기본_기동은_Redis_락이다(monkeypatch):
    body = _config_response(monkeypatch, PMS_LOCK_ENABLED="true")
    assert body["loadTest"]["PMS_LOCK_ENABLED"] is True
    assert body["implementations"]["LockPort"] == "RedisLockAdapter"


def test_T89c_구현체_이름은_실물에서_나온다(monkeypatch):
    """가짜 락을 `override`로 주입하면 응답이 그 가짜의 이름을 보고해야 한다.

    손으로 적은 문자열이면 이 테스트가 잡는다 — 응답과 배선이 어긋날 수
    있다는 뜻이기 때문이다.
    """

    class PlantedFakeLock:
        def acquire_all(self, keys, *, wait_s, ttl_s):  # noqa: ANN001
            raise NotImplementedError

    app = create_app()
    app.state.container.reservation.lock.override(PlantedFakeLock())
    with TestClient(app) as client:
        body = client.get("/api/internal/config").json()
    assert body["implementations"]["LockPort"] == "PlantedFakeLock"


def test_T89d_결제_포트도_실물이_보고된다(monkeypatch):
    body = _config_response(monkeypatch)
    assert body["implementations"]["PaymentPort"] == "FakePaymentAdapter"


def test_processId는_응답을_만든_프로세스다(monkeypatch):
    """F04의 단일 프로세스 확인용 — GET 두 번에 pid가 다르면 멀티 워커다.

    워커 수 설정값이 아니라 실물(pid)을 보고한다.
    """
    body = _config_response(monkeypatch)
    assert body["processId"] == os.getpid()
