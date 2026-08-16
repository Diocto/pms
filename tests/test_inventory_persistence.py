"""재고 차감·복원 조건부 UPDATE (테스트 T38~T42·T45, 스펙 3.2절).

읽고-판단하고-쓰는 세 단계를 UPDATE 한 문장으로 줄인다. `rowcount`가 0이면
재고가 부족했던 것이다 — 락도 재시도도 필요 없다.

시드에 의존하지 않는다. 각 테스트가 자기 행을 넣고 지운다 (스펙 1.8절).
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager
from app.inventory.domain.errors import (
    InsufficientInventoryError,
    InventoryRestoreMismatchError,
)
from app.inventory.domain.models import RoomDailyInventory
from app.inventory.infrastructure.persistence import MySqlInventoryRepository

ROOM_TYPE_ID = 901  # 시드(1~5)와 절대 겹치지 않는 전용 id
DATES = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
NOW = datetime(2026, 8, 15, 12, 0, 0)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (901, '테스트 호텔 901', '테스트 주소', NOW(6))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price, created_at)"
                " VALUES (:id, 901, '테스트 타입 901', 2, 10, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID},
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM hotel WHERE id = 901"))
    engine.dispose()


@pytest.fixture()
def tx(engine):
    """매 테스트 전에 전용 재고 행 3개를 잔여 10으로 리셋한다."""
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
                    " VALUES (:id, :d, 10, 10, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": stay_date},
            )
    return TransactionManager(sessionmaker(bind=engine))


@pytest.fixture()
def repository():
    return MySqlInventoryRepository()


def _remaining(engine, stay_date: date) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT remaining FROM room_daily_inventory"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": ROOM_TYPE_ID, "d": stay_date},
        ).scalar_one()


def test_T38_잔여가_충분하면_전_날짜가_깎인다(tx, repository, engine):
    """재고 조건부 UPDATE — 전 날짜의 잔여가 충분하면 요청 수만큼 모든 날짜가
    깎인다(10 → 7). 차감의 정상 경로다."""
    with tx.write() as session:
        repository.deduct(
            session, room_type_id=ROOM_TYPE_ID, stay_dates=DATES, room_count=3, now=NOW
        )
    assert [_remaining(engine, d) for d in DATES] == [7, 7, 7]


def test_T39_잔여가_부족하면_예외이고_아무_행도_안_깎인다(tx, repository, engine):
    """재고 조건부 UPDATE — 잔여(10)보다 많은 11을 요청하면
    InsufficientInventoryError가 나고 어느 행도 깎이지 않는다. rowcount 0을
    재고 부족으로 판정하는 계약의 확인이다."""
    with pytest.raises(InsufficientInventoryError):
        with tx.write() as session:
            repository.deduct(
                session,
                room_type_id=ROOM_TYPE_ID,
                stay_dates=DATES,
                room_count=11,
                now=NOW,
            )
    assert [_remaining(engine, d) for d in DATES] == [10, 10, 10]


def test_T39b_가운데_날짜만_부족해도_앞_날짜_차감분이_롤백된다(tx, repository, engine):
    """재고 조건부 UPDATE — 가운데 날짜만 부족해도 앞 날짜에서 깎인 분량이
    write() 블록의 예외 롤백으로 함께 되돌아간다. 부분 차감이 남으면 아무도
    안 묵는데 팔 수 없는 유령 점유가 생긴다."""
    # K7의 단일 스레드 판. 부분 차감이 남으면 유령 점유가 생긴다
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = 2"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": ROOM_TYPE_ID, "d": DATES[1]},
        )
    with pytest.raises(InsufficientInventoryError):
        with tx.write() as session:
            repository.deduct(
                session,
                room_type_id=ROOM_TYPE_ID,
                stay_dates=DATES,
                room_count=3,
                now=NOW,
            )
    # 첫 날짜(10)도 그대로다 — write() 블록 예외로 전체 롤백
    assert [_remaining(engine, d) for d in DATES] == [10, 2, 10]


def test_T40_잔여와_요청이_같으면_경계에서_성공한다(tx, repository, engine):
    """재고 조건부 UPDATE — 잔여와 요청이 같은 경계값(잔여 10에 10개 요청)에서
    성공해 잔여가 0이 된다. `remaining >= :count` 조건의 등호가 살아 있는지
    본다. 부등호로 잘못 짜면 마지막 방이 영원히 안 팔린다."""
    with tx.write() as session:
        repository.deduct(
            session,
            room_type_id=ROOM_TYPE_ID,
            stay_dates=[DATES[0]],
            room_count=10,
            now=NOW,
        )
    assert _remaining(engine, DATES[0]) == 0


def test_T41_복원은_깎인_만큼_되돌린다(tx, repository, engine):
    """재고 조건부 UPDATE — 취소·만료 복원이 깎인 만큼 정확히 되돌린다
    (4 차감 뒤 4 복원 → 다시 10). 차감과 복원이 짝을 이루는 정상 경로다."""
    with tx.write() as session:
        repository.deduct(
            session, room_type_id=ROOM_TYPE_ID, stay_dates=DATES, room_count=4, now=NOW
        )
    with tx.write() as session:
        repository.restore(
            session, room_type_id=ROOM_TYPE_ID, stay_dates=DATES, room_count=4, now=NOW
        )
    assert [_remaining(engine, d) for d in DATES] == [10, 10, 10]


def test_T42_총량을_넘는_복원은_이중_복원_감지로_실패한다(tx, repository, engine):
    """재고 조건부 UPDATE — 깎은 적 없는 상태의 복원(총량 초과)은
    InventoryRestoreMismatchError로 실패하고 아무 행도 안 바뀐다. 이중 복원이
    조용히 재고를 부풀리는 것을 막는다."""
    # 깎지 않은 상태에서 복원 = 이중 복원 시나리오. 조용히 넘기지 않는다
    with pytest.raises(InventoryRestoreMismatchError):
        with tx.write() as session:
            repository.restore(
                session,
                room_type_id=ROOM_TYPE_ID,
                stay_dates=DATES,
                room_count=1,
                now=NOW,
            )
    assert [_remaining(engine, d) for d in DATES] == [10, 10, 10]


def test_T45_벌크_UPDATE_뒤_같은_세션의_객체는_낡아_있다(tx, repository, engine):
    """identity map은 조건부 UPDATE를 모른다 — JPA 1차 캐시 불일치와 같은 문제다.

    이 사실 자체를 테스트로 고정한다. 이게 깨진다는 것은 SQLAlchemy 동작이
    바뀌었다는 뜻이고, '벌크 UPDATE 뒤에 같은 객체를 읽지 마라' 규칙의
    전제가 흔들린 것이다.
    """
    with tx.write() as session:
        loaded = session.get(RoomDailyInventory, (ROOM_TYPE_ID, DATES[0]))
        assert loaded is not None and loaded.remaining == 10

        repository.deduct(
            session,
            room_type_id=ROOM_TYPE_ID,
            stay_dates=[DATES[0]],
            room_count=3,
            now=NOW,
        )
        # 같은 세션에 이미 로드된 객체는 옛 값을 그대로 갖고 있다
        assert loaded.remaining == 10

        # 갱신 후 값이 필요하면 expire 뒤 다시 읽는다
        session.expire(loaded)
        refreshed = session.get(RoomDailyInventory, (ROOM_TYPE_ID, DATES[0]))
        assert refreshed.remaining == 7
