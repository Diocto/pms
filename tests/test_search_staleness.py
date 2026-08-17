"""C3 — 낡음의 상한 증명 (스펙 9절, TDD 19, T10).

캐시가 낡을 수 있다는 것(허용)과, 낡음이 걷히는 수단이 실제로 동작한다는
것(TTL·evict)을 한 흐름에서 단언한다. TTL 만료는 기다리지 않는다 —
잔여 TTL은 Redis `TTL` 명령으로 보고, 걷기는 `evict_hotel`로 한다.
"""

from datetime import date, datetime, timedelta

import pytest
import redis as redis_library
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.clock import KST, FixedClock
from app.common.db import TransactionManager
from app.inventory.query.application.commands import (
    SearchAvailableRoomsQuery,
    Source,
    StayRange,
)
from app.inventory.query.application.usecases.search_available_rooms import (
    SearchAvailableRoomsUseCase,
)
from app.inventory.query.infrastructure.cache import RedisAvailabilityCacheAdapter
from app.inventory.query.infrastructure.persistence import (
    MySqlAvailabilityQueryAdapter,
)

pytestmark = pytest.mark.concurrency

HOTEL_ID = 936
ROOM_TYPE_ID = 9361
CHECK_IN = date(2026, 9, 1)
TTL_SECONDS = 30  # 잔여 TTL이 충분히 남은 상태에서 evict함을 보이기 위해 길게


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, '검색 낡음 호텔', '검색 테스트 주소', NOW(6))"
            ),
            {"id": HOTEL_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price,"
                "  created_at)"
                " VALUES (:id, :hotel, '검색 낡음 타입', 2, 10, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID, "hotel": HOTEL_ID},
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(
            text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID}
        )
        conn.execute(text("DELETE FROM hotel WHERE id = :id"), {"id": HOTEL_ID})
    engine.dispose()


def _query(fresh: bool = False) -> SearchAvailableRoomsQuery:
    return SearchAvailableRoomsQuery(
        hotel_id=HOTEL_ID,
        stay=StayRange(check_in=CHECK_IN, check_out=CHECK_IN + timedelta(days=3)),
        guest_count=2,
        room_count=1,
        fresh=fresh,
    )


def test_C3_낡음은_허용되고_evict가_상한을_당긴다(engine, redis_url):
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        for offset in range(3):
            # 가운데 날짜만 잔여 1 — minRemaining=1의 출처를 한 행으로 좁힌다
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining,"
                    "  created_at, updated_at)"
                    " VALUES (:id, :d, 10, :r, NOW(6), NOW(6))"
                ),
                {
                    "id": ROOM_TYPE_ID,
                    "d": CHECK_IN + timedelta(days=offset),
                    "r": 1 if offset == 1 else 10,
                },
            )

    redis_client = redis_library.Redis.from_url(redis_url, decode_responses=False)
    for key in redis_client.scan_iter(match=f"avail:{HOTEL_ID}:*"):
        redis_client.delete(key)
    cache = RedisAvailabilityCacheAdapter(redis_client, ttl_seconds=TTL_SECONDS)
    usecase = SearchAvailableRoomsUseCase(
        transaction_manager=TransactionManager(sessionmaker(bind=engine)),
        query_adapter=MySqlAvailabilityQueryAdapter(),
        cache=cache,
        clock=FixedClock(datetime(2026, 8, 16, 12, 0, 0, tzinfo=KST)),
        stale_tolerance_seconds=TTL_SECONDS,
    )
    key = _query().cache_key()

    try:
        # 1) 검색 — minRemaining 1을 확인하고 캐시가 적재된다
        first = usecase.execute(_query())
        assert first.source is Source.DB
        assert first.items[0].min_remaining == 1

        # 2) 재고가 0이 된다 (예약 코어의 차감을 테스트 전용 SQL로 흉내낸다)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE room_daily_inventory SET remaining = 0"
                    " WHERE room_type_id = :id AND stay_date = :d"
                ),
                {"id": ROOM_TYPE_ID, "d": CHECK_IN + timedelta(days=1)},
            )

        # 3) 즉시 재검색 — 옛 값(1)이 나온다. 버그가 아니라 **허용된 결과**다.
        #    이 단언이 "검색은 신선함을 약속하지 않는다"(G2)의 코드 형태다
        stale = usecase.execute(_query())
        assert stale.source is Source.CACHE
        assert stale.items[0].min_remaining == 1

        # 4) evict 직전 — 키가 실제로 존재하고 TTL이 충분히 남아 있음을
        #    확인한다. 이게 없으면 "TTL 만료가 지워놓고 evict가 지운 척"
        #    하는 헛통과가 가능하다 (9절 헛통과 표 C3)
        assert redis_client.get(key) is not None
        remaining_ttl = redis_client.ttl(key)
        assert remaining_ttl > TTL_SECONDS // 2, f"잔여 TTL {remaining_ttl}초"

        cache.evict_hotel(HOTEL_ID)
        assert redis_client.get(key) is None  # evict가 실제로 지웠다

        # 5) evict 후 재검색 — 반드시 새 값이다. 잔여 0이 된 타입은
        #    HAVING MIN >= roomCount에서 사라지는 것이 이 쿼리의 0 관측이다
        refreshed = usecase.execute(_query())
        assert refreshed.source is Source.DB
        assert all(i.room_type_id != ROOM_TYPE_ID for i in refreshed.items)
    finally:
        for key_bytes in redis_client.scan_iter(match=f"avail:{HOTEL_ID}:*"):
            redis_client.delete(key_bytes)
        redis_client.close()
