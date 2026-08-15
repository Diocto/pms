"""Redis 캐시 어댑터 통합 (스펙 7절, TDD 15~17, T7).

TTL 만료를 기다리지 않는다 — TTL이 걸렸는지는 Redis `TTL` 명령으로 본다.
I5(만료 없는 적재)는 유일하게 회복 불가인 실패라 맨 앞에 둔다.
"""

from datetime import date, datetime

import pytest
import redis as redis_library

from app.common.clock import KST
from app.inventory.query.application.commands import (
    AvailableRoomsResult,
    AvailableRoomTypeView,
    EmptyReason,
    SearchAvailableRoomsQuery,
    Source,
    StayRange,
)
from app.inventory.query.infrastructure.cache import RedisAvailabilityCacheAdapter

HOTEL_ID = 934
TTL_SECONDS = 10

RESULT = AvailableRoomsResult(
    searched_at=datetime(2026, 8, 16, 12, 0, 0, tzinfo=KST),
    source=Source.DB,
    stale_tolerance_seconds=TTL_SECONDS,
    items=[
        AvailableRoomTypeView(
            room_type_id=9341,
            room_type_name="캐시 타입",
            capacity=2,
            min_remaining=3,
            price_per_night=100000,
            total_price=300000,
        )
    ],
)


def _query(check_in: date = date(2026, 9, 1), guest_count: int = 2):
    return SearchAvailableRoomsQuery(
        hotel_id=HOTEL_ID,
        stay=StayRange(check_in=check_in, check_out=date(2026, 9, 4)),
        guest_count=guest_count,
        room_count=1,
    )


@pytest.fixture()
def redis_client(redis_url):
    client = redis_library.Redis.from_url(redis_url, decode_responses=False)
    yield client
    for key in client.scan_iter(match=f"avail:{HOTEL_ID}:*"):
        client.delete(key)
    client.close()


@pytest.fixture()
def adapter(redis_client):
    return RedisAvailabilityCacheAdapter(redis_client, ttl_seconds=TTL_SECONDS)


# --- TDD 15. 적재한 항목에 TTL이 설정값으로 걸려 있다 (I5) ---


def test_T15_적재하면_TTL이_설정값으로_걸린다(adapter, redis_client):
    key = _query().cache_key()
    adapter.put(key, RESULT)
    ttl = redis_client.ttl(key)
    # 방금 걸었으므로 (0, TTL] 범위여야 한다. -1(만료 없음)이면 I5 재현이다
    assert 0 < ttl <= TTL_SECONDS, f"TTL이 {ttl}이다 — 만료 없는 적재는 회복 불가다"


def test_적재_후_조회하면_같은_값이_나온다(adapter):
    key = _query().cache_key()
    adapter.put(key, RESULT)
    loaded = adapter.get(key)
    assert loaded == RESULT  # searched_at·items까지 전부 (frozen 값 비교)


def test_없는_키는_None이다(adapter):
    assert adapter.get(_query(guest_count=4).cache_key()) is None


# --- TDD 16. 빈 결과도 캐시된다 ---


def test_T16_빈_결과도_emptyReason째로_캐시된다(adapter):
    empty = AvailableRoomsResult(
        searched_at=RESULT.searched_at,
        source=Source.DB,
        stale_tolerance_seconds=TTL_SECONDS,
        items=[],
        empty_reason=EmptyReason.NOT_YET_OPEN,
        sales_open_until=date(2026, 10, 29),
    )
    key = _query(check_in=date(2026, 9, 2)).cache_key()
    adapter.put(key, empty)
    loaded = adapter.get(key)
    assert loaded is not None
    assert loaded.items == []
    assert loaded.empty_reason is EmptyReason.NOT_YET_OPEN
    assert loaded.sales_open_until == date(2026, 10, 29)


# --- evict_hotel — 호텔 단위로 전부 지운다 ---


def test_evict_hotel은_그_호텔의_모든_키를_지운다(adapter):
    key_a = _query().cache_key()
    key_b = _query(guest_count=3).cache_key()
    adapter.put(key_a, RESULT)
    adapter.put(key_b, RESULT)
    adapter.evict_hotel(HOTEL_ID)
    assert adapter.get(key_a) is None
    assert adapter.get(key_b) is None


def test_evict_hotel은_다른_호텔_키를_건드리지_않는다(adapter, redis_client):
    other_key = f"avail:9999{HOTEL_ID}:2026-09-01:2026-09-04:2:1"
    redis_client.set(other_key, b"{}", ex=TTL_SECONDS)
    adapter.put(_query().cache_key(), RESULT)
    adapter.evict_hotel(HOTEL_ID)
    try:
        assert redis_client.get(other_key) is not None
    finally:
        redis_client.delete(other_key)


# --- TDD 17. I8 재현 — 무효화 뒤 늦게 도착한 적재가 낡은 값을 남기고,
#     TTL이 그것을 걷어간다 ---


def test_T17_무효화_뒤_늦은_적재는_낡은_값을_남기지만_TTL이_상한이다(
    adapter, redis_client
):
    key = _query().cache_key()

    # 1) 정상 적재 → 2) 무효화가 지나간다 → 3) 그보다 먼저 읽어둔 낡은
    # 스냅샷이 뒤늦게 도착해 적재된다 (I8의 실패 순서)
    adapter.put(key, RESULT)
    adapter.evict_hotel(HOTEL_ID)
    stale = RESULT.model_copy(
        update={"items": [RESULT.items[0].model_copy(update={"min_remaining": 99})]}
    )
    adapter.put(key, stale)

    # 낡은 값이 실제로 앉았다 — 무효화는 이것을 못 막는다
    loaded = adapter.get(key)
    assert loaded is not None
    assert loaded.items[0].min_remaining == 99

    # 그러나 TTL이 걸려 있어 스스로 걷힌다. 이 단언이 이 설계의 척추다 —
    # 누가 "이벤트 무효화를 붙였으니 TTL을 빼자"고 하면 여기가 먼저 깨진다
    ttl = redis_client.ttl(key)
    assert 0 < ttl <= TTL_SECONDS, "낡은 값에 만료가 없다 — 영구히 남는다 (I8+I5)"
