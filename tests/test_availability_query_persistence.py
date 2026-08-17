"""집계 쿼리 어댑터 영속성 통합 (스펙 8절 집계 쿼리, TDD 4·4b·5·6, T4).

시드에 의존하지 않는다. 전용 호텔 930과 객실타입 9301·9302를 넣고 지운다.
재고 행 조작은 전부 테스트 전용 SQL이다 — 검색 프로덕션 경로는 SELECT만 한다.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager
from app.inventory.query.application.commands import (
    SearchAvailableRoomsQuery,
    StayRange,
)
from app.inventory.query.infrastructure.persistence import MySqlAvailabilityQueryAdapter

HOTEL_ID = 930  # 시드(1~2)·다른 테스트(901~905)와 겹치지 않는 검색 전용 대역
CHEAP_TYPE = 9301  # capacity 2, 총 5실, 100,000원
WIDE_TYPE = 9302  # capacity 4, 총 3실, 200,000원
DATES = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, '검색 테스트 호텔', '검색 테스트 주소', NOW(6))"
            ),
            {"id": HOTEL_ID},
        )
        for type_id, capacity, quantity, price in (
            (CHEAP_TYPE, 2, 5, 100000),
            (WIDE_TYPE, 4, 3, 200000),
        ):
            conn.execute(
                text(
                    "INSERT INTO room_type"
                    " (id, hotel_id, name, capacity, total_quantity, base_price,"
                    "  created_at)"
                    " VALUES (:id, :hotel, :name, :capacity, :qty, :price, NOW(6))"
                ),
                {
                    "id": type_id,
                    "hotel": HOTEL_ID,
                    "name": f"검색 타입 {type_id}",
                    "capacity": capacity,
                    "qty": quantity,
                    "price": price,
                },
            )
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM room_daily_inventory"
                " WHERE room_type_id IN (:a, :b)"
            ),
            {"a": CHEAP_TYPE, "b": WIDE_TYPE},
        )
        conn.execute(
            text("DELETE FROM room_type WHERE hotel_id = :id"), {"id": HOTEL_ID}
        )
        conn.execute(text("DELETE FROM hotel WHERE id = :id"), {"id": HOTEL_ID})
    engine.dispose()


@pytest.fixture()
def tx(engine):
    """매 테스트 전에 두 타입 × 3일 재고를 총량 그대로 리셋한다."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM room_daily_inventory WHERE room_type_id IN (:a, :b)"
            ),
            {"a": CHEAP_TYPE, "b": WIDE_TYPE},
        )
        for type_id, quantity in ((CHEAP_TYPE, 5), (WIDE_TYPE, 3)):
            for stay_date in DATES:
                conn.execute(
                    text(
                        "INSERT INTO room_daily_inventory"
                        " (room_type_id, stay_date, total_quantity, remaining,"
                        "  created_at, updated_at)"
                        " VALUES (:id, :d, :q, :q, NOW(6), NOW(6))"
                    ),
                    {"id": type_id, "d": stay_date, "q": quantity},
                )
    return TransactionManager(sessionmaker(bind=engine))


@pytest.fixture()
def adapter():
    return MySqlAvailabilityQueryAdapter()


def _query(guest_count: int = 2, room_count: int = 1) -> SearchAvailableRoomsQuery:
    return SearchAvailableRoomsQuery(
        hotel_id=HOTEL_ID,
        stay=StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        guest_count=guest_count,
        room_count=room_count,
    )


def _set_remaining(engine, type_id: int, stay_date: date, remaining: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = :r"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"r": remaining, "id": type_id, "d": stay_date},
        )


# --- TDD 4. 기간의 모든 날짜에 재고가 있어야 결과에 나온다 ---


def test_T4_기간_전체를_덮으면_두_타입이_나온다(tx, adapter):
    with tx.read() as session:
        items = adapter.search(session, _query())
    assert [item.room_type_id for item in items] == [CHEAP_TYPE, WIDE_TYPE]


def test_T4_가운데_날짜_행이_없으면_그_타입은_빠진다(tx, adapter, engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM room_daily_inventory"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": WIDE_TYPE, "d": date(2026, 9, 2)},
        )
    with tx.read() as session:
        items = adapter.search(session, _query())
    # 행이 없는 날짜는 "제약 없음"이 아니라 "가용 아님"이다 (D9 fail-closed)
    assert [item.room_type_id for item in items] == [CHEAP_TYPE]


def test_T4_체크아웃_당일_행이_없어도_가용이다(tx, adapter, engine):
    # 9/4는 체크아웃 당일이라 점유하지 않는다. 그 날 행이 없어도 결과는 그대로다
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM room_daily_inventory WHERE stay_date = :d"
                " AND room_type_id IN (:a, :b)"
            ),
            {"d": date(2026, 9, 4), "a": CHEAP_TYPE, "b": WIDE_TYPE},
        )
    with tx.read() as session:
        items = adapter.search(session, _query())
    assert [item.room_type_id for item in items] == [CHEAP_TYPE, WIDE_TYPE]


# --- TDD 4b. 세션 경계 두 개 — 주면 동작하고, 안 주면 실패한다 ---


def test_T4b_세션을_주면_동작한다(tx, adapter):
    with tx.read() as session:
        items = adapter.search(session, _query())
    assert len(items) == 2


def test_T4b_세션_없이_부르면_실패한다(adapter):
    # 어댑터가 스스로 세션을 열지 못한다. 열 수 있으면 트랜잭션이 둘로 갈라진다
    with pytest.raises(TypeError):
        adapter.search(query=_query())  # type: ignore[call-arg]
    with pytest.raises(AttributeError):
        adapter.search(None, _query())  # type: ignore[arg-type]


# --- TDD 5. 기간 중 최소 잔여가 minRemaining으로 나온다 ---


def test_T5_기간_중_가장_빡빡한_날의_잔여가_나온다(tx, adapter, engine):
    _set_remaining(engine, CHEAP_TYPE, date(2026, 9, 2), 3)
    _set_remaining(engine, CHEAP_TYPE, date(2026, 9, 3), 4)
    with tx.read() as session:
        items = adapter.search(session, _query())
    cheap = next(item for item in items if item.room_type_id == CHEAP_TYPE)
    assert cheap.min_remaining == 3


def test_T5_가격은_1박_단가와_기간_총액으로_나온다(tx, adapter):
    with tx.read() as session:
        items = adapter.search(session, _query())
    cheap, wide = items
    assert (cheap.price_per_night, cheap.total_price) == (100000, 300000)  # 3박
    assert (wide.price_per_night, wide.total_price) == (200000, 600000)
    assert cheap.room_type_name == f"검색 타입 {CHEAP_TYPE}"
    assert (cheap.capacity, wide.capacity) == (2, 4)


def test_T5_총액에는_객실_수가_곱해진다(tx, adapter):
    with tx.read() as session:
        items = adapter.search(session, _query(guest_count=2, room_count=2))
    # 총액 = 1박 단가 × 박수 × 객실 수 (스펙 8절). 예약 코어 예약 청구액과 같은 식이라
    # 여기가 어긋나면 검색 견적과 실제 청구액이 2실 이상에서 항상 갈라진다
    cheap = next(item for item in items if item.room_type_id == CHEAP_TYPE)
    assert cheap.total_price == 100000 * 3 * 2


def test_T5_잔여가_요청_객실_수_미만인_날이_있으면_빠진다(tx, adapter, engine):
    _set_remaining(engine, WIDE_TYPE, date(2026, 9, 3), 1)
    with tx.read() as session:
        items = adapter.search(session, _query(guest_count=2, room_count=2))
    # WIDE는 9/3 잔여 1 < 2. CHEAP은 capacity 2 × 2실 = 4 ≥ 2 이고 잔여 5
    assert [item.room_type_id for item in items] == [CHEAP_TYPE]


# --- TDD 6. 인원 필터 ---


def test_T6_정원을_넘는_인원이면_아무것도_나오지_않는다(tx, adapter):
    with tx.read() as session:
        items = adapter.search(session, _query(guest_count=5, room_count=1))
    # capacity 최대 4 × 1실 = 4 < 5. 시드 데이터에서도 같은 경계다 (계약 문서 2절)
    assert items == []


def test_T6_객실_수를_늘리면_정원_합으로_통과한다(tx, adapter):
    with tx.read() as session:
        items = adapter.search(session, _query(guest_count=5, room_count=2))
    # CHEAP: 2×2=4 < 5 탈락. WIDE: 4×2=8 ≥ 5, 잔여 3 ≥ 2 통과
    assert [item.room_type_id for item in items] == [WIDE_TYPE]
