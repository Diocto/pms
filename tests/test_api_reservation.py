"""예약 API 통합 — 라우터부터 DB까지 (계획 C-1~C-3의 API 판, 스펙 2장).

시드에 의존하지 않는다 — 전용 객실타입(id=903)과 재고 행을 직접 만든다.
상태 코드와 에러 코드가 계약 표(2.1절)와 일치하는지가 이 파일의 관심사다.
"""

import os
from datetime import date, timedelta

import pytest
import redis as redis_library
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.common.clock import SystemClock
from app.main import create_app

ROOM_TYPE_ID = 903
TODAY = SystemClock().today()
IN_1 = date(2026, 9, 1)
OUT_4 = date(2026, 9, 4)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (903, '테스트 호텔 903', '주소', NOW(6))"
                " ON DUPLICATE KEY UPDATE name = name"
            )
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price, created_at)"
                " VALUES (:id, 903, '테스트 타입 903', 2, 5, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID},
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reservation_status_history WHERE reservation_id IN (SELECT id FROM reservation WHERE room_type_id = :id)"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM hotel WHERE id = 903"))
    engine.dispose()


@pytest.fixture()
def client(engine, database_url, redis_url, monkeypatch):
    monkeypatch.setenv("PMS_DATABASE_URL", database_url)
    monkeypatch.setenv("PMS_REDIS_URL", redis_url)

    # 재고 리셋: 오늘부터 30일 + 9월 구간, 잔여 5
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM reservation_status_history WHERE reservation_id IN (SELECT id FROM reservation WHERE room_type_id = :id)"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        dates = {TODAY + timedelta(days=offset) for offset in range(7)}
        dates |= {IN_1 + timedelta(days=offset) for offset in range(7)}
        for stay_date in sorted(dates):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining, created_at, updated_at)"
                    " VALUES (:id, :d, 5, 5, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": stay_date},
            )

    redis_client = redis_library.Redis.from_url(redis_url)
    redis_client.flushdb()
    redis_client.close()

    app = create_app()
    # 500도 '응답'으로 받아 계약(코드·롤백)을 검증한다 (T68)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _remaining(engine, stay_date: date) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT remaining FROM room_daily_inventory"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": ROOM_TYPE_ID, "d": stay_date},
        ).scalar_one()


def _create(client, *, user="user-api-1", key="idem-api-1", check_in=IN_1,
            check_out=OUT_4, room_count=1, guest_count=2, room_type_id=ROOM_TYPE_ID,
            discounts=None):
    body = {
        "roomTypeId": room_type_id,
        "checkIn": str(check_in),
        "checkOut": str(check_out),
        "roomCount": room_count,
        "guestCount": guest_count,
    }
    if discounts is not None:
        body["discounts"] = discounts
    return client.post(
        "/api/reservations",
        json=body,
        headers={"X-User-Id": user, "Idempotency-Key": key},
    )


# ── 생성 (T46~T54) ──────────────────────────────────────────────────

def test_T46_정상_생성은_201이고_재고가_깎이고_응답이_camelCase다(client, engine):
    response = _create(client)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["totalPrice"] == 300000  # 100000 × 3박 × 1실 — camelCase 확인 겸
    assert "id" not in body and "idempotencyKey" not in body  # 내부 필드 비노출
    assert _remaining(engine, IN_1) == 4


def test_T49_멱등_재요청은_200과_같은_본문이다(client, engine):
    first = _create(client, key="idem-replay").json()
    second = _create(client, key="idem-replay")
    assert second.status_code == 200  # 최초 201과 상태 코드로 구분 (D18)
    assert second.json()["confirmationCode"] == first["confirmationCode"]
    assert _remaining(engine, IN_1) == 4  # 두 번 깎이지 않았다


def test_T51_입력_오류는_400이고_키가_지워져_고친_재시도가_성공한다(client):
    bad = _create(client, key="idem-fix", guest_count=99)  # 정원 2×1=2 초과
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_REQUEST"
    good = _create(client, key="idem-fix", guest_count=2)
    assert good.status_code == 201  # 키가 남아 있었으면 409였다


def test_T52_재고_부족은_409이고_같은_키_재요청도_같은_409다(client, engine):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE room_daily_inventory SET remaining = 0 WHERE room_type_id = :id AND stay_date = :d"),
            {"id": ROOM_TYPE_ID, "d": IN_1},
        )
    first = _create(client, key="idem-full")
    assert first.status_code == 409
    assert first.json()["code"] == "INSUFFICIENT_INVENTORY"
    # D30 — 재요청이 REQUEST_IN_PROGRESS로 둔갑하지 않는다
    second = _create(client, key="idem-full")
    assert second.status_code == 409
    assert second.json()["code"] == "INSUFFICIENT_INVENTORY"


def test_T47_가운데_날짜만_부족하면_앞_날짜_차감분도_롤백된다(client, engine):
    middle = IN_1 + timedelta(days=1)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE room_daily_inventory SET remaining = 0 WHERE room_type_id = :id AND stay_date = :d"),
            {"id": ROOM_TYPE_ID, "d": middle},
        )
    response = _create(client, key="idem-partial")
    assert response.status_code == 409
    assert _remaining(engine, IN_1) == 5  # 부분 차감이 남지 않았다


def test_T48_없는_객실타입은_404다(client):
    response = _create(client, key="idem-404", room_type_id=99999)
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


def test_재고_행이_없는_날짜는_409_재고_부족이다(client):
    response = _create(
        client, key="idem-norow",
        check_in=date(2026, 11, 1), check_out=date(2026, 11, 3),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INSUFFICIENT_INVENTORY"


def test_T53_락이_막히면_503이고_키가_지워져_재시도가_성공한다(client, redis_url):
    lock_key = f"lock:inventory:{ROOM_TYPE_ID}:{IN_1}"
    holder = redis_library.Redis.from_url(redis_url)
    holder.set(lock_key, "someone-else")
    try:
        blocked = _create(client, key="idem-lock")
        assert blocked.status_code == 503
        assert blocked.json()["code"] == "LOCK_ACQUISITION_FAILED"
    finally:
        holder.delete(lock_key)
        holder.close()
    retry = _create(client, key="idem-lock")
    assert retry.status_code == 201  # 503은 그대로 재시도하면 되는 실패다


def test_헤더가_없으면_400_INVALID_REQUEST다(client):
    response = client.post(
        "/api/reservations",
        json={"roomTypeId": 1, "checkIn": "2026-09-01", "checkOut": "2026-09-02",
              "roomCount": 1, "guestCount": 1},
        headers={"X-User-Id": "user-1"},  # Idempotency-Key 누락
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


# ── 조회·확정 (T57~T62) ─────────────────────────────────────────────

def test_조회는_소유자만_보이고_남의_예약은_404다(client):
    code = _create(client, user="owner-1", key="idem-get").json()["confirmationCode"]
    mine = client.get(f"/api/reservations/{code}", headers={"X-User-Id": "owner-1"})
    assert mine.status_code == 200
    others = client.get(f"/api/reservations/{code}", headers={"X-User-Id": "intruder"})
    assert others.status_code == 404  # 존재 자체를 알려주지 않는다


def test_T57_확정_성공은_CONFIRMED이고_재고는_불변이다(client, engine):
    code = _create(client, key="idem-confirm").json()["confirmationCode"]
    before = _remaining(engine, IN_1)
    response = client.post(
        f"/api/reservations/{code}/confirm", headers={"X-User-Id": "user-api-1"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert body["confirmedAt"] is not None
    assert _remaining(engine, IN_1) == before  # 재고는 생성 때 이미 확보했다


def test_T59_이미_확정된_예약의_재확정은_200이고_결제를_다시_부르지_않는다(client):
    code = _create(client, key="idem-reconfirm").json()["confirmationCode"]
    payment = client.app.state.container.reservation.payment()
    client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "user-api-1"})
    charged_before = len(payment.charged)
    again = client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "user-api-1"})
    assert again.status_code == 200
    assert again.json()["status"] == "CONFIRMED"
    assert len(payment.charged) == charged_before  # 결제를 다시 부르지 않았다
    assert payment.refunded == []                  # 보상도 없다


def test_T58_결제_거절은_200_CANCELLED이고_재고가_복원된다(client, engine):
    code = _create(client, key="idem-decline").json()["confirmationCode"]
    container = client.app.state.container
    from app.reservation.infrastructure.payment import FakePaymentAdapter

    container.reservation.payment.override(FakePaymentAdapter(decline_rate=1.0))
    try:
        response = client.post(
            f"/api/reservations/{code}/confirm", headers={"X-User-Id": "user-api-1"}
        )
    finally:
        container.reservation.payment.reset_override()
    assert response.status_code == 200  # 에러가 아니라 정상 흐름의 결과다
    body = response.json()
    assert body["status"] == "CANCELLED"
    assert body["failureReason"] == "PAYMENT_DECLINED"
    assert _remaining(engine, IN_1) == 5  # 복원됐다


def test_T60_만료_대기_중인_예약의_확정은_409이고_결제를_부르지_않는다(client, engine):
    code = _create(client, key="idem-late").json()["confirmationCode"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reservation SET expires_at = NOW(6) - INTERVAL 1 MINUTE WHERE confirmation_code = :c"),
            {"c": code},
        )
    payment = client.app.state.container.reservation.payment()
    charged_before = len(payment.charged)
    response = client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "user-api-1"})
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"
    assert len(payment.charged) == charged_before  # 만료 대기 중 — 결제를 부르지 않았다


def test_남의_예약_확정은_404이고_결제를_부르지_않는다(client):
    # 관리자 지시 (2026-08-16, D33). 확인번호만 알면 제3자가 남의 결제를
    # 일으킬 수 있던 문을 닫는다 — 취소·조회와 같은 규칙이다
    code = _create(client, user="owner-3", key="idem-d33").json()["confirmationCode"]
    payment = client.app.state.container.reservation.payment()
    charged_before = len(payment.charged)
    response = client.post(
        f"/api/reservations/{code}/confirm", headers={"X-User-Id": "stranger"}
    )
    assert response.status_code == 404
    assert len(payment.charged) == charged_before


def test_취소된_예약의_확정은_409이고_결제를_부르지_않는다(client):
    # 2.3절 실패 표 3행. 표 수준(T13)이 아니라 API 경로로 확인한다
    code = _create(client, user="u", key="idem-conf-cancelled").json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": "u"})
    payment = client.app.state.container.reservation.payment()
    charged_before = len(payment.charged)
    response = client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "u"})
    assert response.status_code == 409
    assert len(payment.charged) == charged_before


def test_T64_확정된_예약의_취소도_재고를_복원한다(client, engine):
    code = _create(client, user="u64", key="idem-t64").json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "u64"})
    assert _remaining(engine, IN_1) == 4
    response = client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": "u64"})
    assert response.status_code == 200
    assert _remaining(engine, IN_1) == 5
    assert _history_rows(engine, code) == [
        ("PENDING", "CONFIRM", "CONFIRMED"),
        ("CONFIRMED", "CANCEL", "CANCELLED"),
    ]


def test_T68_복원_갱신_수_불일치는_조용히_넘기지_않고_500이다(client, engine):
    code = _create(client, user="u68", key="idem-t68").json()["confirmationCode"]
    # 이중 복원 상황의 재현 — 잔여를 이미 총량으로 만들어 복원이 0건이 되게 한다
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE room_daily_inventory SET remaining = total_quantity WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
    response = client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": "u68"})
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    # 트랜잭션 롤백 — 상태도 이력도 남지 않았다
    body = client.get(f"/api/reservations/{code}", headers={"X-User-Id": "u68"}).json()
    assert body["status"] == "PENDING"
    assert _history_rows(engine, code) == []


def test_이미_체크인된_예약의_체크인_재요청은_200_멱등이다(client):
    # 2.6절 표의 멱등 칸 — 시간창 검증을 건너뛰는 분기까지 이 경로가 덮는다
    code = _confirmed_today(client, "idem-recheckin")
    client.post(f"/api/reservations/{code}/check-in", headers={"X-User-Id": "guest"})
    again = client.post(f"/api/reservations/{code}/check-in", headers={"X-User-Id": "guest"})
    assert again.status_code == 200
    assert again.json()["status"] == "CHECKED_IN"


def test_T25b_포맷을_따르지_않는_확인번호도_전_경로가_정상_동작한다(client, engine):
    """만드는 함수만 있고 읽는 함수는 없다 (D7). 어딘가에서 포맷을 파싱하거나
    형식 검사를 걸면 이 테스트가 깨진다."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reservation"
                " (confirmation_code, user_id, room_type_id, check_in, check_out,"
                "  room_count, guest_count, price_per_night, total_price, status,"
                "  idempotency_key, expires_at, created_at, updated_at)"
                " VALUES ('zzz', 'u25b', :rt, :ci, :co, 1, 2, 100000, 300000,"
                "  'PENDING', 'idem-zzz', '2026-12-31 23:59:59', NOW(6), NOW(6))"
            ),
            {"rt": ROOM_TYPE_ID, "ci": str(IN_1), "co": str(OUT_4)},
        )
        # 합성 예약이므로 점유분을 수동으로 차감해 둔다 — 안 하면 취소의
        # 복원이 총량을 넘어 이중 복원 감지(정상 작동)에 걸린다
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = remaining - 1"
                " WHERE room_type_id = :rt AND stay_date >= :ci AND stay_date < :co"
            ),
            {"rt": ROOM_TYPE_ID, "ci": str(IN_1), "co": str(OUT_4)},
        )
    assert client.get("/api/reservations/zzz", headers={"X-User-Id": "u25b"}).status_code == 200
    confirm = client.post("/api/reservations/zzz/confirm", headers={"X-User-Id": "u25b"})
    assert confirm.status_code == 200 and confirm.json()["status"] == "CONFIRMED"
    cancel = client.post("/api/reservations/zzz/cancel", headers={"X-User-Id": "u25b"})
    assert cancel.status_code == 200 and cancel.json()["status"] == "CANCELLED"


# ── 취소·만료 (T63~T71) ─────────────────────────────────────────────

def _history_rows(engine, code: str) -> list[tuple]:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT h.from_status, h.event, h.to_status"
                " FROM reservation_status_history h"
                " JOIN reservation r ON r.id = h.reservation_id"
                " WHERE r.confirmation_code = :c ORDER BY h.id"
            ),
            {"c": code},
        ).all()


def test_T63_PENDING_취소는_복원과_이력_한_줄이다(client, engine):
    code = _create(client, user="canceller", key="idem-cancel").json()["confirmationCode"]
    response = client.post(
        f"/api/reservations/{code}/cancel", headers={"X-User-Id": "canceller"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert _remaining(engine, IN_1) == 5
    assert _history_rows(engine, code) == [("PENDING", "CANCEL", "CANCELLED")]


def test_T65_이미_취소된_예약의_재취소는_200이고_복원이_안_늘어난다(client, engine):
    code = _create(client, user="canceller", key="idem-recancel").json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": "canceller"})
    again = client.post(
        f"/api/reservations/{code}/cancel", headers={"X-User-Id": "canceller"}
    )
    assert again.status_code == 200
    assert _remaining(engine, IN_1) == 5  # 이중 복원 없음
    assert len(_history_rows(engine, code)) == 1  # 이력도 한 줄 그대로


def test_T67_남의_예약_취소는_403이_아니라_404다(client):
    code = _create(client, user="owner-2", key="idem-theft").json()["confirmationCode"]
    response = client.post(
        f"/api/reservations/{code}/cancel", headers={"X-User-Id": "thief"}
    )
    assert response.status_code == 404


def test_T66_만료된_예약의_취소는_409다__이미_취소됨이_아니라_만료됨(client, engine):
    code = _create(client, user="u", key="idem-exp-cancel").json()["confirmationCode"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reservation SET expires_at = NOW(6) - INTERVAL 1 MINUTE WHERE confirmation_code = :c"),
            {"c": code},
        )
    client.post("/api/internal/reservations/expire")
    response = client.post(f"/api/reservations/{code}/cancel", headers={"X-User-Id": "u"})
    assert response.status_code == 409
    assert "EXPIRED" in response.json()["message"]  # 만료됐다고 답한다


def test_만료_트리거는_기한_지난_PENDING만_EXPIRED로_옮기고_복원한다(client, engine):
    due = _create(client, user="u", key="idem-due").json()["confirmationCode"]
    alive = _create(
        client, user="u", key="idem-alive",
        check_in=IN_1 + timedelta(days=4), check_out=IN_1 + timedelta(days=5),
    ).json()["confirmationCode"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reservation SET expires_at = NOW(6) - INTERVAL 1 MINUTE WHERE confirmation_code = :c"),
            {"c": due},
        )
    response = client.post("/api/internal/reservations/expire")
    assert response.status_code == 200
    assert response.json()["expiredCount"] == 1
    assert client.get(f"/api/reservations/{due}", headers={"X-User-Id": "u"}).json()["status"] == "EXPIRED"
    assert client.get(f"/api/reservations/{alive}", headers={"X-User-Id": "u"}).json()["status"] == "PENDING"
    assert _remaining(engine, IN_1) == 5  # due의 3박이 복원됐다


# ── 체크인·아웃 (T72) ───────────────────────────────────────────────

def _confirmed_today(client, key: str) -> str:
    code = _create(
        client, user="guest", key=key,
        check_in=TODAY, check_out=TODAY + timedelta(days=2),
    ).json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "guest"})
    return code


def test_T71_배치_중_한_건이_실패해도_나머지는_계속_처리된다(client, engine):
    a = _create(client, user="u71", key="idem-t71a").json()["confirmationCode"]
    b = _create(
        client, user="u71", key="idem-t71b",
        check_in=IN_1 + timedelta(days=4), check_out=IN_1 + timedelta(days=5),
    ).json()["confirmationCode"]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reservation SET expires_at = NOW(6) - INTERVAL 1 MINUTE WHERE confirmation_code IN (:a, :b)"),
            {"a": a, "b": b},
        )

    from app.inventory.infrastructure.persistence import MySqlInventoryRepository

    class FailsOnce(MySqlInventoryRepository):
        def __init__(self) -> None:
            self.failed = False

        def restore(self, session, **kwargs):
            if not self.failed:
                self.failed = True
                raise RuntimeError("첫 건의 복원이 실패한다")
            return super().restore(session, **kwargs)

    container = client.app.state.container
    container.reservation.inventory_repository.override(FailsOnce())
    try:
        response = client.post("/api/internal/reservations/expire")
    finally:
        container.reservation.inventory_repository.reset_override()
    # 한 건은 실패(롤백·로그), 다른 한 건은 계속 처리됐다
    assert response.json()["expiredCount"] == 1
    statuses = {
        client.get(f"/api/reservations/{c}", headers={"X-User-Id": "u71"}).json()["status"]
        for c in (a, b)
    }
    assert statuses == {"PENDING", "EXPIRED"}


def test_T72_체크인_체크아웃_정상_흐름(client):
    code = _confirmed_today(client, "idem-checkin")
    check_in = client.post(f"/api/reservations/{code}/check-in", headers={"X-User-Id": "guest"})
    assert check_in.status_code == 200
    assert check_in.json()["status"] == "CHECKED_IN"
    check_out = client.post(f"/api/reservations/{code}/check-out", headers={"X-User-Id": "guest"})
    assert check_out.status_code == 200
    assert check_out.json()["status"] == "CHECKED_OUT"


def test_T72_PENDING_체크인은_409다(client):
    code = _create(client, user="guest", key="idem-early",
                   check_in=TODAY, check_out=TODAY + timedelta(days=2)).json()["confirmationCode"]
    response = client.post(f"/api/reservations/{code}/check-in", headers={"X-User-Id": "guest"})
    assert response.status_code == 409


def test_T72_도착_전_체크인은_409다(client):
    code = _create(client, user="guest", key="idem-future",
                   check_in=IN_1, check_out=OUT_4).json()["confirmationCode"]
    client.post(f"/api/reservations/{code}/confirm", headers={"X-User-Id": "guest"})
    response = client.post(f"/api/reservations/{code}/check-in", headers={"X-User-Id": "guest"})
    assert response.status_code == 409  # 2026-09-01은 아직 오지 않았다
