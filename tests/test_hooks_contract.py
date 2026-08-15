"""확장 지점 4종의 계약 (테스트 T74~T80g, 스펙 3.6절) — F02가 기대는 보장들.

핵심 둘:
- **세션 분리 판별** — "훅이 예외를 던지면 롤백"(T79)만으로는 못 잡는다.
  갈라진 세션도 커밋 전이라 함께 롤백되기 때문이다. **훅이 성공하고 그 뒤
  호출부가 실패하는 경로**(T79b·T79c)만이 분리를 잡는다.
- **호출 위치와 순서** — 사전 검사는 락보다 앞(D23), 해석 → 차감 → INSERT →
  생성 훅(3.6절), 반납 훅은 전이에서 이긴 쪽만.
"""

from datetime import date, timedelta

import pytest
import redis as redis_library
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.common.clock import SystemClock
from app.common.errors import ConflictError
from app.inventory.domain.models import Money
from app.main import create_app
from app.reservation.application.ports import AppliedDiscount

ROOM_TYPE_ID = 904
IN_1 = date(2026, 9, 10)
OUT_3 = date(2026, 9, 12)
USER = "hook-user"


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (904, '테스트 호텔 904', '주소', NOW(6))"
                " ON DUPLICATE KEY UPDATE name = name"
            )
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price, created_at)"
                " VALUES (:id, 904, '테스트 타입 904', 4, 5, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID},
        )
        # 훅이 쓰는 행을 담는 검증 테이블 — F02 테이블의 대역이다
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS hook_probe ("
                "  id BIGINT AUTO_INCREMENT PRIMARY KEY, note VARCHAR(100) NOT NULL)"
            )
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS hook_probe"))
        conn.execute(text("DELETE FROM reservation_status_history WHERE reservation_id IN (SELECT id FROM reservation WHERE room_type_id = :id)"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM hotel WHERE id = 904"))
    engine.dispose()


@pytest.fixture()
def client(engine, database_url, redis_url, monkeypatch):
    monkeypatch.setenv("PMS_DATABASE_URL", database_url)
    monkeypatch.setenv("PMS_REDIS_URL", redis_url)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM hook_probe"))
        conn.execute(text("DELETE FROM reservation_status_history WHERE reservation_id IN (SELECT id FROM reservation WHERE room_type_id = :id)"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        for offset in range(3):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining, created_at, updated_at)"
                    " VALUES (:id, :d, 5, 5, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": IN_1 + timedelta(days=offset)},
            )
    redis_client = redis_library.Redis.from_url(redis_url)
    redis_client.flushdb()
    redis_client.close()
    app = create_app()
    # 예상 못 한 예외도 500 '응답'으로 받는다 — 계약(코드·롤백)을 검증하는 자리다
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.state.container.reservation.creation_hooks.reset_override()
    app.state.container.reservation.release_hooks.reset_override()
    app.state.container.reservation.pre_check_hooks.reset_override()
    app.state.container.reservation.discount_resolvers.reset_override()
    app.state.container.reservation.lock.reset_override()


def _create(client, *, key: str, discounts=None):
    body = {
        "roomTypeId": ROOM_TYPE_ID, "checkIn": str(IN_1), "checkOut": str(OUT_3),
        "roomCount": 1, "guestCount": 2,
    }
    if discounts is not None:
        body["discounts"] = discounts
    return client.post(
        "/api/reservations", json=body,
        headers={"X-User-Id": USER, "Idempotency-Key": key},
    )


def _remaining(engine, stay_date: date) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT remaining FROM room_daily_inventory WHERE room_type_id = :id AND stay_date = :d"),
            {"id": ROOM_TYPE_ID, "d": stay_date},
        ).scalar_one()


def _probe_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM hook_probe")).scalar_one()


class RecordingCreationHook:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def on_created(self, session, reservation_id, command) -> None:
        self.calls.append((reservation_id, command.user_id))


class WritingCreationHook:
    """호출부의 세션으로 행을 쓴다 — F02 사용권 발급의 대역."""

    def on_created(self, session, reservation_id, command) -> None:
        session.execute(text("INSERT INTO hook_probe (note) VALUES ('creation')"))


class RaisingCreationHook:
    def on_created(self, session, reservation_id, command) -> None:
        raise ConflictError("특가 매진", code="INSUFFICIENT_INVENTORY")


class RecordingReleaseHook:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, str]] = []

    def on_released(self, session, reservation_id, from_status, event) -> None:
        self.calls.append((reservation_id, from_status.value, event.value))


def test_T74_훅이_0개여도_생성과_취소가_그대로_돈다(client):
    # 기본 컨테이너가 빈 리스트다 — F02 병합 전에도 F01이 돌아간다는 보장
    code = _create(client, key="k-t74").json()["confirmationCode"]
    response = client.post(
        f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER}
    )
    assert response.status_code == 200


def test_T75_T80_생성_훅은_INSERT_직후_id와_함께_전부_호출된다(client):
    first, second = RecordingCreationHook(), RecordingCreationHook()
    client.app.state.container.reservation.creation_hooks.override([first, second])
    _create(client, key="k-t75")
    assert len(first.calls) == 1 and len(second.calls) == 1  # 둘 다 (T80)
    reservation_id, user = first.calls[0]
    assert reservation_id is not None and user == USER  # id 확정 후 (T75)


def test_T76_T77_반납_훅은_전이에서_이긴_쪽만_정확히_한_번이다(client):
    hook = RecordingReleaseHook()
    client.app.state.container.reservation.release_hooks.override([hook])
    code = _create(client, key="k-t76").json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER})
    assert hook.calls == [(hook.calls[0][0], "PENDING", "CANCEL")]  # 정확히 1회, 인자 정확
    # 재취소(멱등)는 호출되지 않는다 (T77)
    client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER})
    assert len(hook.calls) == 1


def test_T78_체크아웃은_반납_훅을_부르지_않는다(client, engine):
    hook = RecordingReleaseHook()
    client.app.state.container.reservation.release_hooks.override([hook])
    today = SystemClock().today()
    with engine.begin() as conn:
        for offset in range(2):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining, created_at, updated_at)"
                    " VALUES (:id, :d, 5, 5, NOW(6), NOW(6))"
                    " ON DUPLICATE KEY UPDATE remaining = remaining"
                ),
                {"id": ROOM_TYPE_ID, "d": today + timedelta(days=offset)},
            )
    body = {
        "roomTypeId": ROOM_TYPE_ID, "checkIn": str(today),
        "checkOut": str(today + timedelta(days=2)), "roomCount": 1, "guestCount": 2,
    }
    code = client.post(
        "/api/reservations", json=body,
        headers={"X-User-Id": USER, "Idempotency-Key": "k-t78"},
    ).json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": USER})
    client.post(f"/api/reservations/{code}/check-in", headers={"X-User-Id": USER})
    client.post(f"/api/reservations/{code}/check-out", headers={"X-User-Id": USER})
    assert hook.calls == []  # 재고를 복원하지 않는 종료와 같은 대칭 (1.4절)


def test_T79_훅이_던지면_예약도_차감도_전부_롤백된다(client, engine):
    client.app.state.container.reservation.creation_hooks.override(
        [WritingCreationHook(), RaisingCreationHook()]
    )
    response = _create(client, key="k-t79")
    assert response.status_code == 409
    assert _remaining(engine, IN_1) == 5          # 차감 롤백
    assert _probe_count(engine) == 0              # 훅이 쓴 행도 롤백
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM reservation WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        ).scalar_one()
    assert count == 0                             # INSERT도 롤백


def test_T79b_훅이_성공한_뒤_호출부가_실패하면_훅이_쓴_행도_사라진다(client, engine):
    """세션 분리를 잡는 유일한 판별 테스트다.

    훅이 자기 세션을 열었다면 그 세션은 이미 커밋되어 probe 행이 살아남는다 —
    T79는 이것을 못 잡는다 (갈라진 세션도 예외 시에는 함께 롤백되므로).
    """

    class FailsAfter(WritingCreationHook):
        pass

    class CallerFails:
        def on_created(self, session, reservation_id, command) -> None:
            # 훅(위)이 성공한 뒤 호출부 흐름의 다음 단계가 실패하는 상황의 재현
            raise RuntimeError("호출부의 그다음 단계가 실패했다")

    client.app.state.container.reservation.creation_hooks.override(
        [FailsAfter(), CallerFails()]
    )
    response = _create(client, key="k-t79b")
    assert response.status_code == 500
    assert _probe_count(engine) == 0  # 살아남았다면 훅이 별도 세션을 쓴 것이다


def test_T79c_반납_훅_성공_뒤_실패도_함께_롤백된다(client, engine):
    """반납 쪽 세션 분리 판별 (2회차 리뷰에서 확인한 공백). 갈라지면
    "취소는 안 됐는데 특가만 복원된" — 같은 방을 두 번 파는 상태가 된다."""

    class WritingRelease:
        def on_released(self, session, reservation_id, from_status, event) -> None:
            session.execute(text("INSERT INTO hook_probe (note) VALUES ('release')"))

    class FailingRelease:
        def on_released(self, session, reservation_id, from_status, event) -> None:
            raise RuntimeError("반납 처리의 다음 단계가 실패했다")

    client.app.state.container.reservation.release_hooks.override(
        [WritingRelease(), FailingRelease()]
    )
    code = _create(client, key="k-t79c").json()["confirmationCode"]
    response = client.post(
        f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER}
    )
    assert response.status_code == 500
    assert _probe_count(engine) == 0                      # 훅의 행 롤백
    assert _remaining(engine, IN_1) == 4                  # 복원도 롤백 (여전히 차감 상태)
    status = client.get(
        f"/api/reservations/{code}", headers={"X-User-Id": USER}
    ).json()["status"]
    assert status == "PENDING"                            # 취소도 롤백


# ── 해석기 (T80a~T80e, D22) ─────────────────────────────────────────

class FixedResolver:
    def __init__(self, price: int | None) -> None:
        self._price = price
        self.calls: list[str] = []

    def resolve(self, session, ref, room_type_id, period):
        self.calls.append(ref.reference)
        if self._price is None:
            return None
        return AppliedDiscount(ref=ref, price_per_night=Money(amount=self._price))


def test_T80a_할인이_없으면_정가이고_해석기를_부르지_않는다(client):
    resolver = FixedResolver(price=70000)
    client.app.state.container.reservation.discount_resolvers.override([resolver])
    body = _create(client, key="k-t80a").json()
    assert body["pricePerNight"] == 100000  # base_price
    assert resolver.calls == []


def test_T80b_해석_성공은_특가_단가가_스냅샷된다(client):
    resolver = FixedResolver(price=70000)
    client.app.state.container.reservation.discount_resolvers.override([resolver])
    body = _create(
        client, key="k-t80b",
        discounts=[{"type": "PROMOTION", "reference": "promo-1"}],
    ).json()
    assert body["pricePerNight"] == 70000       # 실제 청구 단가 (D22)
    assert body["totalPrice"] == 140000         # 70000 × 2박 × 1실
    assert resolver.calls == ["promo-1"]


def test_T80c_해석_실패는_400이다__정가로_조용히_넘어가지_않는다(client):
    client.app.state.container.reservation.discount_resolvers.override(
        [FixedResolver(price=None)]
    )
    response = _create(
        client, key="k-t80c",
        discounts=[{"type": "PROMOTION", "reference": "promo-x"}],
    )
    assert response.status_code == 400  # fail-closed


def test_T80d_할인_2개는_400이다(client):
    response = _create(
        client, key="k-t80d",
        discounts=[
            {"type": "PROMOTION", "reference": "a"},
            {"type": "PROMOTION", "reference": "b"},
        ],
    )
    assert response.status_code == 400


# ── 사전 검사 (T80f·T80g, D23) ──────────────────────────────────────

class CountingLock:
    def __init__(self) -> None:
        self.acquired = 0

    def acquire_all(self, keys, *, wait_s, ttl_s):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            self.acquired += 1
            yield

        return _cm()


class RejectingPreCheck:
    def check(self, command) -> None:
        raise ConflictError("특가가 열리지 않았습니다", code="INSUFFICIENT_INVENTORY")


def test_T80f_사전_검사가_거부하면_락을_잡지_않는다(client):
    lock = CountingLock()
    container = client.app.state.container
    container.reservation.pre_check_hooks.override([RejectingPreCheck()])
    container.reservation.lock.override(lock)
    response = _create(client, key="k-t80f")
    assert response.status_code == 409
    assert lock.acquired == 0  # 락보다 앞이다 — 아끼려던 비용을 안 치렀다 (D23)


def test_T80g_사전_검사_거부의_멱등_키는_실패로_남는다(client):
    client.app.state.container.reservation.pre_check_hooks.override(
        [RejectingPreCheck()]
    )
    first = _create(client, key="k-t80g")
    assert first.status_code == 409
    # 같은 키 재요청 — 재고 부족과 같은 성격이라 같은 결과를 받는다 (D30)
    second = _create(client, key="k-t80g")
    assert second.status_code == 409
    assert second.json()["code"] == first.json()["code"]
