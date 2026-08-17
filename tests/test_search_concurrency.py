"""검색 동시성 C1·C2·C4·C5 (스펙 9절 동시성 표, TDD 18, T9).

시나리오마다 "경합이 실제로 일어났음을 증명하는 단언"을 함께 넣는다 —
전부 순차 실행돼도 통과하는 헛통과를 막기 위해서다 (9절 헛통과 표).

C2의 관측 형태 하나를 적어둔다: 집계 쿼리는 `HAVING MIN(remaining) >=
:roomCount`라 잔여가 0이 되면 그 타입이 **결과에서 사라진다.** 그래서
"minRemaining이 1 또는 0"의 실물 관측은 "minRemaining 1로 존재하거나,
아예 없거나"다. 그 사이 값·부분 결과가 없다는 본질은 같다.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pytest
import redis as redis_library
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.clock import KST, FixedClock
from app.common.db import TransactionManager
from app.inventory.application.commands import (
    SearchAvailableRoomsQuery,
    Source,
    StayRange,
)
from app.inventory.application.usecases.search_available_rooms import (
    SearchAvailableRoomsUseCase,
)
from app.inventory.infrastructure.cache import (
    NoOpAvailabilityCacheAdapter,
    RedisAvailabilityCacheAdapter,
)
from app.inventory.infrastructure.search_persistence import (
    MySqlAvailabilityQueryAdapter,
)

pytestmark = pytest.mark.concurrency

HOTEL_ID = 935
ROOM_TYPE_IDS = [9351, 9352, 9353, 9354, 9355]  # 5종 (스펙 9절 기본 데이터셋)
CONTESTED_TYPE = 9351
BASE_DATE = date(2026, 9, 1)
NIGHTS_SEEDED = 30
NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=KST)
TTL_SECONDS = 10


@pytest.fixture(scope="module")
def engine(database_url):
    # 스레드 수만큼 커넥션이 필요하다. 풀이 작으면 경합이 커넥션 대기로 흡수된다
    engine = create_engine(database_url, pool_size=30, max_overflow=80)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, '검색 동시성 호텔', '검색 테스트 주소', NOW(6))"
            ),
            {"id": HOTEL_ID},
        )
        for index, type_id in enumerate(ROOM_TYPE_IDS):
            conn.execute(
                text(
                    "INSERT INTO room_type"
                    " (id, hotel_id, name, capacity, total_quantity, base_price,"
                    "  created_at)"
                    " VALUES (:id, :hotel, :name, :capacity, 10, :price, NOW(6))"
                ),
                {
                    "id": type_id,
                    "hotel": HOTEL_ID,
                    "name": f"동시성 타입 {type_id}",
                    "capacity": 2 + (index % 3),  # 2·3·4 섞는다
                    "price": 100000 + index * 10000,
                },
            )
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE i FROM room_daily_inventory i"
                " JOIN room_type rt ON rt.id = i.room_type_id"
                " WHERE rt.hotel_id = :hotel"
            ),
            {"hotel": HOTEL_ID},
        )
        conn.execute(
            text("DELETE FROM room_type WHERE hotel_id = :hotel"),
            {"hotel": HOTEL_ID},
        )
        conn.execute(text("DELETE FROM hotel WHERE id = :hotel"), {"hotel": HOTEL_ID})
    engine.dispose()


@pytest.fixture()
def inventory(engine):
    """매 테스트 전에 5종 × 30일 재고를 잔여 10으로 리셋한다."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE i FROM room_daily_inventory i"
                " JOIN room_type rt ON rt.id = i.room_type_id"
                " WHERE rt.hotel_id = :hotel"
            ),
            {"hotel": HOTEL_ID},
        )
        for type_id in ROOM_TYPE_IDS:
            for offset in range(NIGHTS_SEEDED):
                conn.execute(
                    text(
                        "INSERT INTO room_daily_inventory"
                        " (room_type_id, stay_date, total_quantity, remaining,"
                        "  created_at, updated_at)"
                        " VALUES (:id, :d, 10, 10, NOW(6), NOW(6))"
                    ),
                    {"id": type_id, "d": BASE_DATE + timedelta(days=offset)},
                )


@pytest.fixture()
def redis_client(redis_url):
    client = redis_library.Redis.from_url(redis_url, decode_responses=False)
    for key in client.scan_iter(match=f"avail:{HOTEL_ID}:*"):
        client.delete(key)
    yield client
    for key in client.scan_iter(match=f"avail:{HOTEL_ID}:*"):
        client.delete(key)
    client.close()


def _usecase(engine, cache) -> SearchAvailableRoomsUseCase:
    return SearchAvailableRoomsUseCase(
        transaction_manager=TransactionManager(sessionmaker(bind=engine)),
        query_adapter=MySqlAvailabilityQueryAdapter(),
        cache=cache,
        clock=FixedClock(NOW),
        stale_tolerance_seconds=TTL_SECONDS,
    )


def _query(check_in=BASE_DATE, nights=3, guest_count=2, room_count=1, fresh=False):
    return SearchAvailableRoomsQuery(
        hotel_id=HOTEL_ID,
        stay=StayRange(
            check_in=check_in, check_out=check_in + timedelta(days=nights)
        ),
        guest_count=guest_count,
        room_count=room_count,
        fresh=fresh,
    )


def _items_signature(result):
    return tuple(
        (i.room_type_id, i.min_remaining, i.price_per_night, i.total_price)
        for i in result.items
    )


def _run_threads(threads: int, target):
    """배리어로 전원을 모아 함께 출발시키고, (결과, 예외) 목록을 돌려준다."""
    barrier = threading.Barrier(threads)
    results = []
    errors = []
    lock = threading.Lock()

    def attempt():
        try:
            barrier.wait()
            value = target()
            with lock:
                results.append(value)
        except Exception as error:  # noqa: BLE001 — 예상 못 한 것을 세는 자리다
            with lock:
                errors.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:  # Barrier 인원수와 동일
        futures = [pool.submit(attempt) for _ in range(threads)]
    for future in futures:
        future.result()
    return results, errors


# --- C1. 조회 폭주 — 100 스레드 동시 검색, 캐시 on/off 각각 ---


def test_C1_캐시_on_100스레드_동시_검색(engine, inventory, redis_client):
    # 100 전원을 한 배리어에 걸면 "CACHE·DB 둘 다 관찰"이 스케줄링 운에
    # 걸린다 — 전원이 put보다 먼저 get을 지나가면 전부 DB가 나와 위양성
    # 실패가 난다(실측으로 확인). 그래서 한랭 50(동시) + 온기 50(동시)
    # 두 물결로 나눠 두 source의 관찰을 결정적으로 만든다. 각 물결이
    # 배리어 동시 출발이므로 폭주 조건 자체는 그대로다
    usecase = _usecase(
        engine, RedisAvailabilityCacheAdapter(redis_client, ttl_seconds=TTL_SECONDS)
    )
    cold_results, cold_errors = _run_threads(50, lambda: usecase.execute(_query()))
    warm_results, warm_errors = _run_threads(50, lambda: usecase.execute(_query()))

    assert cold_errors == [] and warm_errors == []
    results = cold_results + warm_results
    assert len(results) == 100  # 응답 누락 0건
    signatures = {_items_signature(r) for r in results}
    assert len(signatures) == 1  # 100개 응답의 items가 전부 동일
    # 헛통과 방지 — 한랭 물결에 DB가, 온기 물결에 CACHE가 반드시 있다
    assert Source.DB in {r.source for r in cold_results}
    assert {r.source for r in warm_results} == {Source.CACHE}


def test_C1_캐시_off_100스레드_동시_검색(engine, inventory):
    usecase = _usecase(engine, NoOpAvailabilityCacheAdapter())
    results, errors = _run_threads(100, lambda: usecase.execute(_query()))

    assert errors == []
    assert len(results) == 100
    assert len({_items_signature(r) for r in results}) == 1
    assert {r.source for r in results} == {Source.DB}


# --- C2. 읽기-쓰기 경합 — 잔여 1을 0으로 갱신하는 동안 50 스레드 검색 ---


def test_C2_읽기_쓰기_경합에서_중간값이_없다(engine, inventory):
    # 경합 대상: CONTESTED_TYPE의 가운데 날짜(9/2)만 잔여 1로 좁힌다
    contested_date = BASE_DATE + timedelta(days=1)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = 1"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": CONTESTED_TYPE, "d": contested_date},
        )

    usecase = _usecase(engine, NoOpAvailabilityCacheAdapter())  # 캐시 off

    # 갱신 스레드가 검색 50과 **같은 배리어**에서 출발한다 — 갱신이 물결
    # 사이에서 단독으로 도는 순간 겹침이 0이 되고, 이 시나리오는 헛통과가
    # 된다 (1차 리뷰 지적). 결정성은 물결 분리가 아니라 두 신호로 만든다:
    # ① 갱신은 최소 한 검색이 완료된 뒤에만 커밋한다 → "1 관측"이 보장되고,
    #    그 시점에 나머지 검색들이 한창 돌고 있으므로 겹침이 실재한다.
    # ② 각 검색 스레드는 0을 볼 때까지 반복 조회한다 → "0 관측"이 보장된다.
    observers = 50
    barrier = threading.Barrier(observers + 1)
    first_read_done = threading.Event()
    update_done_at: list[float] = []
    observations: list[tuple[float, int]] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def read_once() -> int:
        result = usecase.execute(_query())
        contested = [
            i for i in result.items if i.room_type_id == CONTESTED_TYPE
        ]
        # 부분 결과 금지: 있으면 반드시 minRemaining 1이다 (0이면 HAVING에서
        # 타입째 사라지는 것이 이 쿼리의 0 관측 형태다)
        if contested:
            assert contested[0].min_remaining == 1
            return 1
        return 0

    def observe():
        try:
            barrier.wait()
            deadline = time.monotonic() + 10
            while True:
                started_at = time.monotonic()
                value = read_once()
                with lock:
                    observations.append((started_at, value))
                first_read_done.set()
                if value == 0 or time.monotonic() > deadline:
                    return
        except Exception as error:  # noqa: BLE001 — 예상 못 한 것을 세는 자리다
            with lock:
                errors.append(error)

    def update_to_zero():
        try:
            barrier.wait()
            assert first_read_done.wait(timeout=10)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE room_daily_inventory SET remaining = 0"
                        " WHERE room_type_id = :id AND stay_date = :d"
                    ),
                    {"id": CONTESTED_TYPE, "d": contested_date},
                )
            update_done_at.append(time.monotonic())
        except Exception as error:  # noqa: BLE001
            with lock:
                errors.append(error)

    with ThreadPoolExecutor(max_workers=observers + 1) as pool:
        futures = [pool.submit(observe) for _ in range(observers)]
        futures.append(pool.submit(update_to_zero))
    for future in futures:
        future.result()

    assert errors == []
    assert update_done_at, "갱신 스레드가 커밋하지 못했다"
    values = [value for _, value in observations]
    # 헛통과 방지 — 1과 0이 모두 나타나야 한다. 한 값만 나오면 경합 미발생이다
    assert set(values) == {1, 0}, f"관찰값: {set(values)}"
    # 겹침의 실증 — 갱신 커밋 시각이 검색 시작 시각들 사이에 떨어졌다
    started_ats = [started for started, _ in observations]
    assert min(started_ats) < update_done_at[0] < max(started_ats)
    # 갱신 완료 이후 시작된 검색은 전부 0 (사라짐)이다
    late = [v for started, v in observations if started > update_done_at[0]]
    assert late and all(v == 0 for v in late)


# --- C4. 캐시 on/off 동등성 — 20가지 조건, items 완전 동일 ---


def test_C4_캐시_on_off_결과_동등성(engine, inventory, redis_client):
    conditions = [
        dict(
            check_in=BASE_DATE + timedelta(days=index),
            nights=1 + index % 3,
            guest_count=1 + index % 4,
            room_count=1 + index % 2,
        )
        for index in range(20)
    ]
    on_usecase = _usecase(
        engine, RedisAvailabilityCacheAdapter(redis_client, ttl_seconds=TTL_SECONDS)
    )
    off_usecase = _usecase(engine, NoOpAvailabilityCacheAdapter())

    on_sources = []
    for condition in conditions:
        first = on_usecase.execute(_query(**condition))  # 빈 캐시에서 적재
        second = on_usecase.execute(_query(**condition))  # 히트
        off = off_usecase.execute(_query(**condition))
        assert _items_signature(first) == _items_signature(off), condition
        assert _items_signature(second) == _items_signature(off), condition
        assert (first.empty_reason, first.sales_open_until) == (
            off.empty_reason,
            off.sales_open_until,
        )
        on_sources += [first.source, second.source]

    # 헛통과 방지 — on 회차에 CACHE가 한 번도 없으면 두 회차가 같은 경로다
    assert Source.CACHE in on_sources
    assert {r for r in on_sources} <= {Source.CACHE, Source.DB}


# --- C5. Redis 장애 폴백 — 정지 확인 후 50회 검색 전부 200 ---


def test_C5_Redis가_죽어도_검색은_전부_성공한다(engine, inventory, caplog):
    import logging

    from testcontainers.community.redis import RedisContainer

    from app.inventory.application.usecases import search_available_rooms

    logging.getLogger(search_available_rooms.__name__).disabled = False

    # 공유 컨테이너를 죽이면 다른 테스트가 무너진다 — 전용 컨테이너를 쓴다
    container = RedisContainer("redis:7.4-alpine")
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        from redis.retry import Retry
        from redis.backoff import NoBackoff

        # redis-py의 내부 재시도(지수 백오프)를 끈다 — 켜두면 죽은 서버에
        # 요청 100번이 수 분짜리 대기가 된다 (실측 402초 → 수 초)
        dead_client = redis_library.Redis(
            host=host,
            port=int(port),
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            retry=Retry(NoBackoff(), 0),
            retry_on_error=[],
        )
        assert dead_client.ping()  # 정지 전에는 살아 있다
    finally:
        container.stop()

    # 헛통과 방지 — 정지가 실제로 됐는지 PING 실패로 확인한 뒤 시작한다
    with pytest.raises(Exception):
        dead_client.ping()

    usecase = _usecase(
        engine, RedisAvailabilityCacheAdapter(dead_client, ttl_seconds=TTL_SECONDS)
    )
    with caplog.at_level("WARNING"):
        results = [usecase.execute(_query()) for _ in range(50)]

    assert len(results) == 50  # 예외 0건 — 여기 도달한 것 자체가 증명이다
    assert {r.source for r in results} == {Source.DB}
    assert len({_items_signature(r) for r in results}) == 1
    # WARN이 남는다 (조회·적재 각 50회)
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 100
