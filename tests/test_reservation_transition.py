"""상태 전이 조건부 UPDATE (테스트 T43·T44, 스펙 3.2절)."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.infrastructure.persistence import MySqlReservationRepository

NOW = datetime(2026, 8, 15, 12, 0, 0)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def reservation_id(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reservation"
                " (confirmation_code, user_id, room_type_id, check_in, check_out,"
                "  room_count, guest_count, price_per_night, total_price, status,"
                "  idempotency_key, expires_at, created_at, updated_at)"
                " VALUES ('TR-0001', 'test-transition-01', 1, '2026-09-01',"
                "  '2026-09-04', 1, 2, 150000, 450000, 'PENDING',"
                "  'idem-tr-0001', NOW(6), NOW(6), NOW(6))"
            )
        )
        inserted = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()
    yield inserted
    with engine.begin() as conn:
        # 자기 예약의 이력만 지운다 (병렬 실행 대비)
        conn.execute(
            text(
                "DELETE FROM reservation_status_history WHERE reservation_id = :id"
            ),
            {"id": inserted},
        )
        conn.execute(text("DELETE FROM reservation WHERE id = :id"), {"id": inserted})


@pytest.fixture()
def tx(engine):
    return TransactionManager(sessionmaker(bind=engine))


def _status(engine, reservation_id: int) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM reservation WHERE id = :id"),
            {"id": reservation_id},
        ).scalar_one()


def test_T43_기대_상태가_일치하면_전이가_1건_성공한다(tx, reservation_id, engine):
    repository = MySqlReservationRepository()
    with tx.write() as session:
        won = repository.transition(
            session,
            reservation_id=reservation_id,
            expected=ReservationStatus.PENDING,
            next_status=ReservationStatus.CONFIRMED,
            now=NOW,
            confirmed_at=NOW,
        )
        assert won is True
        # 이력은 1을 받은 쪽만 쓴다
        repository.append_history(
            session,
            reservation_id=reservation_id,
            from_status=ReservationStatus.PENDING,
            event=ReservationEvent.CONFIRM,
            to_status=ReservationStatus.CONFIRMED,
            occurred_at=NOW,
        )
    assert _status(engine, reservation_id) == "CONFIRMED"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT from_status, event, to_status"
                " FROM reservation_status_history WHERE reservation_id = :id"
            ),
            {"id": reservation_id},
        ).all()
    assert rows == [("PENDING", "CONFIRM", "CONFIRMED")]


def test_T44_기대_상태가_다르면_0건이고_상태는_불변이다(tx, reservation_id, engine):
    repository = MySqlReservationRepository()
    # 먼저 취소시켜 둔다
    with tx.write() as session:
        assert repository.transition(
            session,
            reservation_id=reservation_id,
            expected=ReservationStatus.PENDING,
            next_status=ReservationStatus.CANCELLED,
            now=NOW,
            terminated_at=NOW,
        )
    # 이제 확정을 시도하면 경합에서 진 것과 같은 상황이다
    with tx.write() as session:
        won = repository.transition(
            session,
            reservation_id=reservation_id,
            expected=ReservationStatus.PENDING,
            next_status=ReservationStatus.CONFIRMED,
            now=NOW,
        )
        assert won is False
    assert _status(engine, reservation_id) == "CANCELLED"  # 불변
