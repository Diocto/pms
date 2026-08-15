"""C6 — 검색 → 예약 409 → fresh 재검색 (스펙 9절, TDD 21, T11).

이 스펙의 핵심 서사를 API 전 구간으로 증명한다: 두 사용자가 같은 캐시
스냅샷(잔여 1)을 보고 동시에 예약을 눌러도, 재고는 음수가 되지 않고
정확히 한 명만 성공하며, 진 쪽의 `fresh=true` 재검색에서 그 객실타입이
사라진다 — 경합의 해소가 검색이 아니라 예약 시점임을 보이는 테스트다.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
import redis as redis_library
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app

pytestmark = pytest.mark.concurrency

HOTEL_ID = 937
ROOM_TYPE_ID = 9371
CHECK_IN = date(2026, 9, 1)
CHECK_OUT = date(2026, 9, 4)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, 'F03 서사 호텔', 'F03 테스트 주소', NOW(6))"
            ),
            {"id": HOTEL_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price,"
                "  created_at)"
                " VALUES (:id, :hotel, 'F03 서사 타입', 2, 1, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID, "hotel": HOTEL_ID},
        )
        for offset in range(3):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining,"
                    "  created_at, updated_at)"
                    " VALUES (:id, :d, 1, 1, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": CHECK_IN + timedelta(days=offset)},
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
        conn.execute(
            text("DELETE FROM reservation WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(
            text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID}
        )
        conn.execute(text("DELETE FROM hotel WHERE id = :id"), {"id": HOTEL_ID})
    engine.dispose()


@pytest.fixture(scope="module")
def client(engine, database_url, redis_url):
    import os

    saved = {k: os.environ.get(k) for k in ("PMS_DATABASE_URL", "PMS_REDIS_URL")}
    os.environ["PMS_DATABASE_URL"] = database_url
    os.environ["PMS_REDIS_URL"] = redis_url
    redis_client = redis_library.Redis.from_url(redis_url)
    for key in redis_client.scan_iter(match=f"avail:{HOTEL_ID}:*"):
        redis_client.delete(key)
    redis_client.close()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _search(client, fresh: bool = False):
    return client.get(
        "/api/availability",
        params={
            "hotelId": HOTEL_ID,
            "checkIn": str(CHECK_IN),
            "checkOut": str(CHECK_OUT),
            "guestCount": 2,
            "roomCount": 1,
            "fresh": str(fresh).lower(),
        },
    )


def _reserve(client, user: str):
    return client.post(
        "/api/reservations",
        headers={"X-User-Id": user, "Idempotency-Key": f"c6-{user}"},
        json={
            "roomTypeId": ROOM_TYPE_ID,
            "checkIn": str(CHECK_IN),
            "checkOut": str(CHECK_OUT),
            "roomCount": 1,
            "guestCount": 2,
        },
    )


def _remaining(engine) -> list[int]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT remaining FROM room_daily_inventory"
                " WHERE room_type_id = :id ORDER BY stay_date"
            ),
            {"id": ROOM_TYPE_ID},
        ).scalars()
        return list(rows)


def test_C6_검색_409_재검색_서사(client, engine):
    # 헛통과 방지 — 시작 전 재고가 정확히 1임을 조회로 확인한다.
    # 2 이상이면 둘 다 201이 나야 정상이라 "1건 409"가 검증이 안 된다
    assert _remaining(engine) == [1, 1, 1]

    # 두 사용자가 같은 캐시 스냅샷을 받는다 (첫 검색이 적재, 둘째가 히트)
    first_view = _search(client).json()
    second_view = _search(client).json()
    assert first_view["items"][0]["minRemaining"] == 1
    assert second_view["items"][0]["minRemaining"] == 1
    assert second_view["source"] == "CACHE"  # 실제로 같은 스냅샷이다

    # 같은 잔여 1을 보고 동시에 예약을 누른다
    barrier = threading.Barrier(2)

    def reserve(user: str):
        barrier.wait()
        return _reserve(client, user)

    with ThreadPoolExecutor(max_workers=2) as pool:
        # X-User-Id는 HTTP 헤더라 ASCII만 가능하다
        futures = [pool.submit(reserve, user) for user in ("c6-user-a", "c6-user-b")]
    responses = [future.result() for future in futures]
    status_codes = sorted(r.status_code for r in responses)

    assert status_codes == [201, 409], [r.text for r in responses]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["code"] == "INSUFFICIENT_INVENTORY"

    # 재고 음수 0건 — 잔여는 정확히 0이다
    assert _remaining(engine) == [0, 0, 0]
    # 성공한 예약이 정확히 1건 있다
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM reservation WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        ).scalar_one()
    assert count == 1

    # 진 쪽이 fresh=true로 재검색하면 그 객실타입이 사라져 있다 —
    # 스펙 6절의 "409는 오류 화면이 아니라 재검색 신호" 서사의 완결이다
    retry_view = _search(client, fresh=True).json()
    assert retry_view["source"] == "DB"
    assert all(
        item["roomTypeId"] != ROOM_TYPE_ID for item in retry_view["items"]
    )
    assert retry_view["items"] == []  # 이 호텔엔 타입이 하나뿐이라 빈 결과다
    assert retry_view["emptyReason"] == "SOLD_OUT"
