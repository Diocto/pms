"""예약 목록 API 통합 — GET /api/reservations (F05 요청, 관리자 지시 2026-08-16).

계약: 헤더 `X-User-Id` 필수, 그 사용자의 예약 배열을 **최신순**으로 준다.
원소 형태는 단건 조회의 `ReservationResponse`와 같다 (camelCase).
선택 쿼리 `?status=`는 전이 상태 enum만 받고, 밖의 값은 400이다.

읽기 전용이라 동시성 테스트는 없지만, **남의 예약이 안 섞이는 것**은
반드시 본다 — 이 API의 존재 이유가 "내 것만 보인다"이기 때문이다.

시드에 의존하지 않는다 — 전용 객실타입(id=908)과 재고 행을 직접 만든다.
"""

from datetime import date, timedelta

import pytest
import redis as redis_library
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app

ROOM_TYPE_ID = 908
IN_1 = date(2026, 9, 1)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (908, '테스트 호텔 908', '주소', NOW(6))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price, created_at)"
                " VALUES (:id, 908, '테스트 타입 908', 2, 50, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID},
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM reservation_status_history WHERE reservation_id IN"
                " (SELECT id FROM reservation WHERE room_type_id = :id)"
            ),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM hotel WHERE id = 908"))
    engine.dispose()


@pytest.fixture()
def client(engine, database_url, redis_url, monkeypatch):
    monkeypatch.setenv("PMS_DATABASE_URL", database_url)
    monkeypatch.setenv("PMS_REDIS_URL", redis_url)

    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM reservation_status_history WHERE reservation_id IN"
                " (SELECT id FROM reservation WHERE room_type_id = :id)"
            ),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        for offset in range(10):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining, created_at, updated_at)"
                    " VALUES (:id, :d, 50, 50, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": IN_1 + timedelta(days=offset)},
            )

    redis_client = redis_library.Redis.from_url(redis_url)
    redis_client.flushdb()
    redis_client.close()

    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def _create(client, *, user: str, key: str, day_offset: int = 0) -> str:
    check_in = IN_1 + timedelta(days=day_offset)
    response = client.post(
        "/api/reservations",
        json={
            "roomTypeId": ROOM_TYPE_ID,
            "checkIn": str(check_in),
            "checkOut": str(check_in + timedelta(days=1)),
            "roomCount": 1,
            "guestCount": 2,
        },
        headers={"X-User-Id": user, "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()["confirmationCode"]


def _list(client, user: str, **params):
    return client.get("/api/reservations", params=params, headers={"X-User-Id": user})


def test_내_예약만_최신순으로_나오고_남의_예약은_섞이지_않는다(client):
    first = _create(client, user="list-me", key="idem-list-1", day_offset=0)
    second = _create(client, user="list-me", key="idem-list-2", day_offset=1)
    third = _create(client, user="list-me", key="idem-list-3", day_offset=2)
    _create(client, user="list-other", key="idem-list-other", day_offset=3)

    response = _list(client, "list-me")

    assert response.status_code == 200
    body = response.json()
    assert [item["confirmationCode"] for item in body] == [third, second, first]


def test_원소는_단건_조회_응답과_같은_camelCase_형태다(client):
    code = _create(client, user="list-shape", key="idem-shape")

    single = client.get(
        f"/api/reservations/{code}", headers={"X-User-Id": "list-shape"}
    ).json()
    listed = _list(client, "list-shape").json()

    assert listed == [single]
    assert listed[0]["totalPrice"] == 100000  # camelCase 확인 겸
    assert "id" not in listed[0] and "idempotencyKey" not in listed[0]  # 내부 필드 비노출


def test_status_필터는_그_상태의_예약만_준다(client):
    pending = _create(client, user="list-filter", key="idem-filter-1", day_offset=0)
    confirmed = _create(client, user="list-filter", key="idem-filter-2", day_offset=1)
    client.post(
        f"/api/reservations/{confirmed}/confirm", headers={"X-User-Id": "list-filter"}
    )

    only_confirmed = _list(client, "list-filter", status="CONFIRMED").json()
    only_pending = _list(client, "list-filter", status="PENDING").json()

    assert [item["confirmationCode"] for item in only_confirmed] == [confirmed]
    assert [item["confirmationCode"] for item in only_pending] == [pending]


def test_전이_상태_enum_밖의_status는_400_INVALID_REQUEST다(client):
    response = _list(client, "list-bad-status", status="PAID")

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_헤더가_없으면_400_INVALID_REQUEST다(client):
    response = client.get("/api/reservations")

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_예약이_없는_사용자는_404가_아니라_빈_배열이다(client):
    response = _list(client, "list-nobody")

    assert response.status_code == 200
    assert response.json() == []
