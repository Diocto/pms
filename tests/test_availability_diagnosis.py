"""진단 쿼리와 emptyReason 판정, EXPLAIN 실행 계획 (스펙 8절, TDD 7·8, D8·D9, T5).

진단 쿼리는 집계 결과가 비었을 때만 나간다 — 여기서는 그 쿼리와 판정
순서(404 → NO_FITTING_ROOM_TYPE → NOT_YET_OPEN → SOLD_OUT)를 본다.
전용 호텔 931을 쓰고, 시드 경계(2026-10-29)는 읽기만 하는 시드 호텔 1로 본다.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager
from app.common.errors import NotFoundError
from app.inventory.query.application.commands import (
    EmptyReason,
    SearchAvailableRoomsQuery,
    StayRange,
)
from app.inventory.query.infrastructure.persistence import MySqlAvailabilityQueryAdapter

HOTEL_ID = 931
ROOM_TYPE_ID = 9311  # capacity 2, 총 3실
DATES = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]  # 판매 상한 9/3


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, '검색 진단 테스트 호텔', '검색 테스트 주소', NOW(6))"
            ),
            {"id": HOTEL_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price,"
                "  created_at)"
                " VALUES (:id, :hotel, '검색 진단 타입', 2, 3, 100000, NOW(6))"
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


@pytest.fixture()
def tx(engine):
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        for stay_date in DATES:
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining,"
                    "  created_at, updated_at)"
                    " VALUES (:id, :d, 3, 3, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": stay_date},
            )
    return TransactionManager(sessionmaker(bind=engine))


@pytest.fixture()
def adapter():
    return MySqlAvailabilityQueryAdapter()


def _query(
    hotel_id: int = HOTEL_ID,
    check_in: date = date(2026, 9, 1),
    check_out: date = date(2026, 9, 4),
    guest_count: int = 2,
    room_count: int = 1,
) -> SearchAvailableRoomsQuery:
    return SearchAvailableRoomsQuery(
        hotel_id=hotel_id,
        stay=StayRange(check_in=check_in, check_out=check_out),
        guest_count=guest_count,
        room_count=room_count,
    )


def _diagnose(tx, adapter, query):
    with tx.read() as session:
        return adapter.diagnose(session, query)


# --- TDD 8. 없는 호텔은 404다 (판정 1순위) ---


def test_T8_없는_호텔은_404다(tx, adapter):
    query = _query(hotel_id=999931)
    diagnosis = _diagnose(tx, adapter, query)
    with pytest.raises(NotFoundError):
        diagnosis.empty_reason(query.stay)


# --- TDD 7. 판매 상한을 넘으면 NOT_YET_OPEN이다 (판정 3순위) ---


def test_T7_판매_상한을_넘으면_NOT_YET_OPEN이다(tx, adapter):
    # 재고 행의 마지막 날짜가 9/3인데 마지막 투숙 밤이 9/4다
    query = _query(check_out=date(2026, 9, 5))
    diagnosis = _diagnose(tx, adapter, query)
    assert diagnosis.empty_reason(query.stay) is EmptyReason.NOT_YET_OPEN
    assert diagnosis.sales_open_until == date(2026, 9, 3)


def test_T7_체크아웃_당일은_상한_판정에서도_점유가_아니다(tx, adapter):
    # 마지막 투숙 밤 9/3 = 판매 상한. 행이 다 있으므로 NOT_YET_OPEN이 아니다
    query = _query(check_out=date(2026, 9, 4), room_count=99)  # 잔여 부족으로 빈 결과
    diagnosis = _diagnose(tx, adapter, query)
    assert diagnosis.empty_reason(query.stay) is EmptyReason.SOLD_OUT


def test_T7_시드_경계_2026_10_30을_넘으면_NOT_YET_OPEN이다(tx, adapter):
    # 시드 호텔 1은 읽기만 한다. 재고 마지막 날짜가 2026-10-29이므로
    # 예약 가능한 마지막 checkOut은 2026-10-30이다 (계약 문서 2절)
    query = _query(
        hotel_id=1, check_in=date(2026, 10, 15), check_out=date(2026, 10, 31)
    )
    diagnosis = _diagnose(tx, adapter, query)
    assert diagnosis.empty_reason(query.stay) is EmptyReason.NOT_YET_OPEN
    assert diagnosis.sales_open_until == date(2026, 10, 29)


# --- 판정 2·4순위와 순서 ---


def test_인원이_안_맞으면_NO_FITTING_ROOM_TYPE이다(tx, adapter):
    query = _query(guest_count=5, room_count=1)  # capacity 2 × 1실 = 2 < 5
    diagnosis = _diagnose(tx, adapter, query)
    assert diagnosis.empty_reason(query.stay) is EmptyReason.NO_FITTING_ROOM_TYPE


def test_인원_부적합이_판매_상한보다_먼저다(tx, adapter):
    # 둘 다 해당하면 판정 순서(2 → 3)대로 NO_FITTING_ROOM_TYPE이 이긴다
    query = _query(guest_count=5, room_count=1, check_out=date(2026, 9, 5))
    diagnosis = _diagnose(tx, adapter, query)
    assert diagnosis.empty_reason(query.stay) is EmptyReason.NO_FITTING_ROOM_TYPE


def test_그_외의_빈_결과는_SOLD_OUT이다(tx, adapter, engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = 0"
                " WHERE room_type_id = :id"
            ),
            {"id": ROOM_TYPE_ID},
        )
    query = _query()
    with tx.read() as session:
        assert adapter.search(session, query) == []
    diagnosis = _diagnose(tx, adapter, query)
    assert diagnosis.empty_reason(query.stay) is EmptyReason.SOLD_OUT


# --- Enum 문자열 계약 (부하테스트·화면가 생 문자열로 비교한다) ---


def test_emptyReason_문자열은_계약값_그대로다():
    assert [reason.value for reason in EmptyReason] == [
        "SOLD_OUT",
        "NOT_YET_OPEN",
        "NO_FITTING_ROOM_TYPE",
    ]
    assert all(reason.name == reason.value for reason in EmptyReason)


# --- D8. 실행 계획 — 클러스터드 PK 접근, 풀스캔 없음 ---

BULK_HOTEL_ID = 932  # 객실타입 100종 × 90일 = 재고 9,000행


@pytest.fixture()
def bulk_dataset(engine):
    """실행 계획 검증용 규모 데이터.

    시드 450행 규모에서는 옵티마이저가 비용상 풀스캔+해시 조인을 고르므로
    (PRIMARY가 possible_keys에 있어도 안 쓴다) 장난감 데이터의 EXPLAIN은
    D8 검증이 못 된다. 만 행 규모로 키워야 선택이 의미를 갖는다.
    D13(마이그레이션에 대량 데이터 금지)에 따라 테스트가 넣고 지운다.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, '검색 실행계획 호텔', '검색 테스트 주소', NOW(6))"
            ),
            {"id": BULK_HOTEL_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price,"
                "  created_at)"
                " WITH RECURSIVE n (i) AS"
                "   (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < 99)"
                " SELECT 93200 + i, :hotel, CONCAT('벌크 ', i), 2, 5, 100000,"
                "        NOW(6)"
                "   FROM n"
            ),
            {"hotel": BULK_HOTEL_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_daily_inventory"
                " (room_type_id, stay_date, total_quantity, remaining,"
                "  created_at, updated_at)"
                " WITH RECURSIVE dates (stay_date) AS ("
                "   SELECT CAST('2026-08-01' AS DATE)"
                "   UNION ALL SELECT stay_date + INTERVAL 1 DAY FROM dates"
                "    WHERE stay_date < CAST('2026-10-29' AS DATE))"
                " SELECT rt.id, d.stay_date, 5, 5, NOW(6), NOW(6)"
                "   FROM room_type rt CROSS JOIN dates d"
                "  WHERE rt.hotel_id = :hotel"
            ),
            {"hotel": BULK_HOTEL_ID},
        )
        conn.execute(text("ANALYZE TABLE room_daily_inventory")).fetchall()
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE i FROM room_daily_inventory i"
                " JOIN room_type rt ON rt.id = i.room_type_id"
                " WHERE rt.hotel_id = :hotel"
            ),
            {"hotel": BULK_HOTEL_ID},
        )
        conn.execute(
            text("DELETE FROM room_type WHERE hotel_id = :hotel"),
            {"hotel": BULK_HOTEL_ID},
        )
        conn.execute(
            text("DELETE FROM hotel WHERE id = :hotel"), {"hotel": BULK_HOTEL_ID}
        )


def test_D8_집계_쿼리가_재고_테이블을_풀스캔하지_않는다(engine, bulk_dataset):
    from app.inventory.query.infrastructure.persistence import _SEARCH_SQL

    with engine.connect() as conn:
        rows = conn.execute(
            text("EXPLAIN " + _SEARCH_SQL.text),
            {
                "hotel_id": BULK_HOTEL_ID,
                "check_in": date(2026, 9, 1),
                "check_out": date(2026, 9, 4),
                "guest_count": 2,
                "room_count": 1,
                "nights": 3,
            },
        ).mappings().all()
    inventory_plan = next(row for row in rows if row["table"] == "i")
    # 풀스캔(type=ALL)이면 D8(인덱스 추가 안 함)의 전제가 무너진 것이다 —
    # 그 경우 리비전 301 커버링 인덱스를 관리자 보고 후 재검토한다
    assert inventory_plan["type"] != "ALL", dict(inventory_plan)
    assert inventory_plan["key"] == "PRIMARY", dict(inventory_plan)
