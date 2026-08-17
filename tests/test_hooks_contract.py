"""확장 지점 4종의 계약 (테스트 T74~T80g, 스펙 3.6절) — 선착순 특가가 기대는 보장들.

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
        # 훅이 쓰는 행을 담는 검증 테이블 — 선착순 특가 테이블의 대역이다
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


def _create(client, *, key: str):
    body = {
        "roomTypeId": ROOM_TYPE_ID, "checkIn": str(IN_1), "checkOut": str(OUT_3),
        "roomCount": 1, "guestCount": 2,
    }
    return client.post(
        "/api/reservations", json=body,
        headers={"X-User-Id": USER, "Idempotency-Key": key},
    )


def _execute_with_discounts(client, *, key: str, discounts):
    """할인은 공개 API에 없다 (2.2절, D22) — 선착순 특가처럼 Command를 직접 채워
    유스케이스를 부른다."""
    from app.common.errors import DomainError
    from app.reservation.application.commands import (
        CreateReservationCommand, DiscountRef, DiscountType, OrderLine,
    )
    from app.reservation.domain.models import GuestCount, StayPeriod

    command = CreateReservationCommand(
        user_id=USER,
        idempotency_key=key,
        line=OrderLine(
            room_type_id=ROOM_TYPE_ID,
            stay_period=StayPeriod(check_in=IN_1, check_out=OUT_3),
            room_count=1,
            guest_count=GuestCount(value=2),
        ),
        discounts=[
            DiscountRef(type=DiscountType(item["type"]), reference=item["reference"])
            for item in discounts
        ],
    )
    usecase = client.app.state.container.reservation.create_reservation()
    return usecase.execute(command)


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
    """호출부의 세션으로 행을 쓴다 — 선착순 특가 사용권 발급의 대역."""

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
    """확장 훅 계약(선착순 특가 연동 지점) — 훅이 하나도 등록되지 않아도 생성과 취소가
    그대로 돈다. 선착순 특가 병합 전에도 예약 코어가 단독으로 완결된다는 보장."""
    # 기본 컨테이너가 빈 리스트다 — 선착순 특가 병합 전에도 예약 코어가 돌아간다는 보장
    code = _create(client, key="k-t74").json()["confirmationCode"]
    response = client.post(
        f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER}
    )
    assert response.status_code == 200


def test_T75_T80_생성_훅은_INSERT_직후_id와_함께_전부_호출된다(client):
    """확장 훅 계약(선착순 특가 연동 지점) — 생성 훅은 예약 INSERT 직후 확정된 예약 id를
    받아(T75), 등록된 훅 전부가 각 1회씩 호출된다(T80)."""
    first, second = RecordingCreationHook(), RecordingCreationHook()
    client.app.state.container.reservation.creation_hooks.override([first, second])
    _create(client, key="k-t75")
    assert len(first.calls) == 1 and len(second.calls) == 1  # 둘 다 (T80)
    reservation_id, user = first.calls[0]
    assert reservation_id is not None and user == USER  # id 확정 후 (T75)


def test_T76_T77_반납_훅은_전이에서_이긴_쪽만_정확히_한_번이다(client):
    """확장 훅 계약(선착순 특가 연동 지점) — 반납 훅은 전이에서 이긴 취소만 정확히 한 번,
    이전 상태·이벤트와 함께 부른다(T76). 멱등 재취소는 부르지 않는다(T77) —
    특가 사용권이 두 번 반납되는 것을 막는다."""
    hook = RecordingReleaseHook()
    client.app.state.container.reservation.release_hooks.override([hook])
    code = _create(client, key="k-t76").json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER})
    assert hook.calls == [(hook.calls[0][0], "PENDING", "CANCEL")]  # 정확히 1회, 인자 정확
    # 재취소(멱등)는 호출되지 않는다 (T77)
    client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": USER})
    assert len(hook.calls) == 1


def test_T78_체크아웃은_반납_훅을_부르지_않는다(client, engine):
    """확장 훅 계약(선착순 특가 연동 지점) — 확정·체크인·체크아웃 전 과정에서 반납 훅이
    한 번도 불리지 않는다. 재고를 복원하지 않는 종료(1.4절)와 같은 대칭."""
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
    """확장 훅 계약(선착순 특가 연동 지점) — 생성 훅이 예외를 던지면 409로 응답하고
    예약 INSERT·재고 차감·앞선 훅이 쓴 행까지 전부 롤백된다. 특가 매진인데
    예약만 살아남는 반쪽 상태를 막는다."""
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
    """확장 훅 계약(선착순 특가 연동 지점) — 훅이 성공한 뒤 호출부가 실패해도 훅이 쓴 행이
    함께 롤백된다. 세션 분리를 잡는 유일한 판별 테스트다.

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
    # D31 — 500의 멱등 키는 지워져, 재시도가 가짜 REQUEST_IN_PROGRESS에
    # 갇히지 않고 최초 요청이 된다
    client.app.state.container.reservation.creation_hooks.reset_override()
    retry = _create(client, key="k-t79b")
    assert retry.status_code == 201


def test_T79c_반납_훅_성공_뒤_실패도_함께_롤백된다(client, engine):
    """확장 훅 계약(선착순 특가 연동 지점) — 반납 훅이 성공한 뒤 실패하면 취소·재고 복원·
    훅이 쓴 행이 전부 함께 롤백된다. 반납 쪽 세션 분리 판별 (2회차 리뷰에서 확인한
    공백). 갈라지면 "취소는 안 됐는데 특가만 복원된" — 같은 방을 두 번 파는 상태가 된다."""

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
    """할인 해석기 계약(선착순 특가 연동 지점, D22) — 할인이 없는 일반 예약은 정가
    (base_price)로 계산되고 해석기는 한 번도 불리지 않는다."""
    resolver = FixedResolver(price=70000)
    client.app.state.container.reservation.discount_resolvers.override([resolver])
    body = _create(client, key="k-t80a").json()
    assert body["pricePerNight"] == 100000  # base_price
    assert resolver.calls == []


def test_공개_API는_discounts를_받지_않는다(client):
    """할인 해석기 계약(선착순 특가 연동 지점, D22) — 공개 예약 API에 discounts를 실어 보내도
    무시되어 정가가 적용되고 해석기도 불리지 않는다. 특가 경로 밖에서의 할인
    밀반입을 막는다."""
    # 스펙 2.2: 일반 예약 API에 노출하지 않는다 (D22). 보내도 무시된다
    resolver = FixedResolver(price=1)
    client.app.state.container.reservation.discount_resolvers.override([resolver])
    body = {
        "roomTypeId": ROOM_TYPE_ID, "checkIn": str(IN_1), "checkOut": str(OUT_3),
        "roomCount": 1, "guestCount": 2,
        "discounts": [{"type": "PROMOTION", "reference": "smuggled"}],
    }
    response = client.post(
        "/api/reservations", json=body,
        headers={"X-User-Id": USER, "Idempotency-Key": "k-smuggle"},
    )
    assert response.status_code == 201
    assert response.json()["pricePerNight"] == 100000  # 정가 — 밀반입 무효
    assert resolver.calls == []


def test_T80b_해석_성공은_특가_단가가_스냅샷된다(client):
    """할인 해석기 계약(선착순 특가 연동 지점, D22) — 해석이 성공하면 특가 단가가 예약에
    스냅샷되어 총액까지 특가 기준으로 계산된다."""
    resolver = FixedResolver(price=70000)
    client.app.state.container.reservation.discount_resolvers.override([resolver])
    result = _execute_with_discounts(
        client, key="k-t80b",
        discounts=[{"type": "PROMOTION", "reference": "promo-1"}],
    )
    assert result.price_per_night == 70000      # 실제 청구 단가 (D22)
    assert result.total_price == 140000         # 70000 × 2박 × 1실
    assert resolver.calls == ["promo-1"]


def test_T80c_해석_실패는_400이다__정가로_조용히_넘어가지_않는다(client):
    """할인 해석기 계약(선착순 특가 연동 지점, D22) — 해석기가 None을 돌려주면 도메인
    예외(400)다. 정가로 조용히 넘어가면 특가 조건이 사라진 예약이 손님 모르게
    정가로 청구되므로 fail-closed로 막는다."""
    from app.common.errors import InvalidRequestError

    client.app.state.container.reservation.discount_resolvers.override(
        [FixedResolver(price=None)]
    )
    with pytest.raises(InvalidRequestError):  # fail-closed
        _execute_with_discounts(
            client, key="k-t80c",
            discounts=[{"type": "PROMOTION", "reference": "promo-x"}],
        )


def test_T80d_할인_2개는_400이다(client):
    """할인 해석기 계약(선착순 특가 연동 지점, D22) — 할인을 2개 이상 실으면 도메인
    예외(400)다. 할인은 예약당 최대 1개."""
    from app.common.errors import InvalidRequestError

    with pytest.raises(InvalidRequestError):
        _execute_with_discounts(
            client, key="k-t80d",
            discounts=[
                {"type": "PROMOTION", "reference": "a"},
                {"type": "PROMOTION", "reference": "b"},
            ],
        )


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
    """사전 검사 계약(선착순 특가 연동 지점, D23) — 사전 검사가 거부하면 409로 끝나고
    분산락은 한 번도 잡지 않는다. 어차피 실패할 요청에 락 비용을 치르지 않는다는
    D23의 목적 그 자체."""
    lock = CountingLock()
    container = client.app.state.container
    container.reservation.pre_check_hooks.override([RejectingPreCheck()])
    container.reservation.lock.override(lock)
    response = _create(client, key="k-t80f")
    assert response.status_code == 409
    assert lock.acquired == 0  # 락보다 앞이다 — 아끼려던 비용을 안 치렀다 (D23)


def test_T80g_사전_검사_거부의_멱등_키는_실패로_남는다(client):
    """사전 검사 계약(선착순 특가 연동 지점, D30) — 사전 검사 거부(409)의 멱등 키는 실패로
    남아, 같은 키 재요청도 같은 코드의 409를 받는다. 재고 부족과 같은 성격의 실패."""
    client.app.state.container.reservation.pre_check_hooks.override(
        [RejectingPreCheck()]
    )
    first = _create(client, key="k-t80g")
    assert first.status_code == 409
    # 같은 키 재요청 — 재고 부족과 같은 성격이라 같은 결과를 받는다 (D30)
    second = _create(client, key="k-t80g")
    assert second.status_code == 409
    assert second.json()["code"] == first.json()["code"]
