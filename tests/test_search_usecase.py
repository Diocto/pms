"""검색 유스케이스 (스펙 6절 UC-1, TDD 9~14, T6).

포트를 가짜 구현으로 바꿔 DB 없이 돈다. 여기서 도는지가 포트 분리의 증명이다.
"""

from contextlib import contextmanager
from datetime import date, datetime

import pytest

from app.common.clock import KST, FixedClock
from app.common.errors import InvalidRequestError, NotFoundError
from app.inventory.application.commands import (
    AvailabilityDiagnosis,
    AvailableRoomsResult,
    AvailableRoomTypeView,
    EmptyReason,
    SearchAvailableRoomsQuery,
    Source,
    StayRange,
)
from app.inventory.application.usecases.search_available_rooms import (
    SearchAvailableRoomsUseCase,
)

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=KST)

VIEW = AvailableRoomTypeView(
    room_type_id=1,
    room_type_name="스탠다드",
    capacity=2,
    min_remaining=3,
    price_per_night=100000,
    total_price=300000,
)


class FakeSession:
    pass


class FakeTransactionManager:
    def __init__(self) -> None:
        self.read_count = 0

    @contextmanager
    def read(self):
        self.read_count += 1
        yield FakeSession()


class FakeQueryAdapter:
    def __init__(self, items=None, diagnosis=None) -> None:
        self.items = items if items is not None else [VIEW]
        self.diagnosis = diagnosis
        self.search_calls = 0
        self.diagnose_calls = 0

    def search(self, session, query):
        assert isinstance(session, FakeSession)  # 세션은 유스케이스가 열어 준다
        self.search_calls += 1
        return self.items

    def diagnose(self, session, query):
        assert isinstance(session, FakeSession)
        self.diagnose_calls += 1
        return self.diagnosis


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, AvailableRoomsResult] = {}
        self.get_keys: list[str] = []
        self.put_keys: list[str] = []

    def get(self, key):
        self.get_keys.append(key)
        return self.store.get(key)

    def put(self, key, result):
        self.put_keys.append(key)
        self.store[key] = result

    def evict_hotel(self, hotel_id):  # pragma: no cover - 이 테스트에서 안 쓴다
        raise AssertionError("유스케이스는 evict를 부르지 않는다 (D6)")


class BrokenCache:
    def get(self, key):
        raise ConnectionError("redis down")

    def put(self, key, result):
        raise ConnectionError("redis down")

    def evict_hotel(self, hotel_id):
        raise ConnectionError("redis down")


def _query(guest_count=2, room_count=1, fresh=False, hotel_id=930):
    return SearchAvailableRoomsQuery(
        hotel_id=hotel_id,
        stay=StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        guest_count=guest_count,
        room_count=room_count,
        fresh=fresh,
    )


def _usecase(db=None, cache=None, tolerance=10):
    return SearchAvailableRoomsUseCase(
        transaction_manager=FakeTransactionManager(),
        query_adapter=db if db is not None else FakeQueryAdapter(),
        cache=cache if cache is not None else FakeCache(),
        clock=FixedClock(NOW),
        stale_tolerance_seconds=tolerance,
    )


# --- TDD 9. 캐시가 비어 있으면 DB에서 읽고 source가 DB다 ---


def test_T9_캐시_미스면_DB에서_읽는다():
    db, cache = FakeQueryAdapter(), FakeCache()
    result = _usecase(db, cache).execute(_query())
    assert result.source is Source.DB
    assert result.items == [VIEW]
    assert result.searched_at == NOW
    assert result.stale_tolerance_seconds == 10
    assert db.search_calls == 1
    assert cache.put_keys  # 읽은 결과를 적재한다


def test_T9_적재된_값의_source는_DB_그대로다():
    # source: CACHE는 "지금 이 응답이 캐시에서 왔다"지 값의 속성이 아니다.
    # 적재본에 CACHE를 박으면 미스로 채운 첫 응답과 히트 응답을 구분할 수 없다
    cache = FakeCache()
    _usecase(cache=cache).execute(_query())
    stored = next(iter(cache.store.values()))
    assert stored.source is Source.DB


# --- TDD 10. 캐시 히트면 DB를 부르지 않고 searchedAt이 저장 시각 그대로다 ---


def test_T10_캐시_히트면_DB를_부르지_않는다():
    db, cache = FakeQueryAdapter(), FakeCache()
    stored_at = datetime(2026, 8, 16, 11, 59, 55, tzinfo=KST)
    cache.store[_query().cache_key()] = AvailableRoomsResult(
        searched_at=stored_at,
        source=Source.DB,
        stale_tolerance_seconds=10,
        items=[VIEW],
    )
    result = _usecase(db, cache).execute(_query())
    assert db.search_calls == 0
    assert result.source is Source.CACHE
    # I7 방어 — 응답 시각으로 덮어쓰면 낡음이 숨겨진다 (G2)
    assert result.searched_at == stored_at


# --- TDD 11. fresh=true면 캐시를 건너뛰고 다시 채운다 ---


def test_T11_fresh면_캐시가_있어도_DB를_부르고_다시_채운다():
    db, cache = FakeQueryAdapter(), FakeCache()
    cache.store[_query().cache_key()] = AvailableRoomsResult(
        searched_at=NOW, source=Source.DB, stale_tolerance_seconds=10, items=[]
    )
    result = _usecase(db, cache).execute(_query(fresh=True))
    assert db.search_calls == 1
    assert result.source is Source.DB
    assert cache.get_keys == []  # 읽기 자체를 건너뛴다
    assert cache.store[_query().cache_key()].items == [VIEW]  # 재적재됐다


# --- TDD 12. 캐시 포트가 예외를 던져도 200과 source: DB가 나온다 (D7 fail-open) ---


def test_T12_캐시_장애에도_검색은_동작한다(caplog):
    # 전체 스위트에서는 conftest의 Alembic fileConfig가 로깅을 재구성하며
    # 기존 로거를 비활성화한다(disable_existing_loggers). 이 테스트는 WARN
    # 발생 자체가 관심사이므로 대상 로거를 다시 살리고 잰다
    import logging

    from app.inventory.application.usecases import search_available_rooms

    logging.getLogger(search_available_rooms.__name__).disabled = False

    db = FakeQueryAdapter()
    with caplog.at_level("WARNING"):
        result = _usecase(db, BrokenCache()).execute(_query())
    assert result.source is Source.DB
    assert result.items == [VIEW]
    assert db.search_calls == 1
    # 조회 실패와 적재 실패 각각 WARN이 남는다 (7절 I3·I4)
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 2


# --- TDD 14. 캐시 키에 검색 조건이 전부 반영된다 (I6 방어) ---


def test_T14_키_형식이_계약_그대로다():
    assert _query().cache_key() == "avail:930:2026-09-01:2026-09-04:2:1"


def test_T14_인원과_객실_수가_키를_가른다():
    cache = FakeCache()
    usecase = _usecase(cache=cache)
    usecase.execute(_query(guest_count=2, room_count=1))
    usecase.execute(_query(guest_count=3, room_count=1))
    usecase.execute(_query(guest_count=2, room_count=2))
    assert len(set(cache.put_keys)) == 3


# --- 빈 결과와 404 경로 ---


def test_빈_결과는_진단을_거쳐_이유가_붙는다():
    db = FakeQueryAdapter(
        items=[],
        diagnosis=AvailabilityDiagnosis(
            room_type_count=2,
            fitting_room_type_count=2,
            sales_open_until=date(2026, 9, 10),
        ),
    )
    cache = FakeCache()
    result = _usecase(db, cache).execute(_query())
    assert result.items == []
    assert result.empty_reason is EmptyReason.SOLD_OUT
    assert result.sales_open_until is None  # NOT_YET_OPEN일 때만 싣는다
    assert db.diagnose_calls == 1
    assert cache.put_keys  # 빈 결과도 캐시한다


def test_판매_전이면_salesOpenUntil이_실린다():
    db = FakeQueryAdapter(
        items=[],
        diagnosis=AvailabilityDiagnosis(
            room_type_count=2,
            fitting_room_type_count=2,
            sales_open_until=date(2026, 9, 2),
        ),
    )
    result = _usecase(db).execute(_query())
    assert result.empty_reason is EmptyReason.NOT_YET_OPEN
    assert result.sales_open_until == date(2026, 9, 2)


def test_결과가_있으면_진단_쿼리는_나가지_않는다():
    db = FakeQueryAdapter()
    _usecase(db).execute(_query())
    assert db.diagnose_calls == 0  # 정상 경로는 쿼리 1회


def test_없는_호텔은_404이고_캐시에_남지_않는다():
    db = FakeQueryAdapter(
        items=[],
        diagnosis=AvailabilityDiagnosis(
            room_type_count=0, fitting_room_type_count=0, sales_open_until=None
        ),
    )
    cache = FakeCache()
    with pytest.raises(NotFoundError):
        _usecase(db, cache).execute(_query(hotel_id=999))
    assert cache.put_keys == []


def test_과거_체크인은_주입된_시계로_거부한다():
    # NOW는 2026-08-16. 체크인이 8/15면 과거다 (D14)
    query = SearchAvailableRoomsQuery(
        hotel_id=930,
        stay=StayRange(check_in=date(2026, 8, 15), check_out=date(2026, 8, 20)),
        guest_count=2,
        room_count=1,
    )
    db, cache = FakeQueryAdapter(), FakeCache()
    with pytest.raises(InvalidRequestError):
        _usecase(db, cache).execute(query)
    assert db.search_calls == 0
    assert cache.get_keys == []
