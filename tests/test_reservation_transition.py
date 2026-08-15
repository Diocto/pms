"""상태 전이 적용 — `apply_event` (테스트 T43·T44, 스펙 3.2절).

**표가 유일한 공급원이다** (2회차 리뷰 반영). 호출자는 이벤트만 던지고,
다음 상태·이력 값·복원 여부는 전부 표에서 나온다. 표 밖 조합은 UPDATE에
도달하기 전에 예외다.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.errors import InvalidStateTransitionError
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


def _row(engine, reservation_id: int) -> tuple:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT status, confirmed_at IS NOT NULL, terminated_at IS NOT NULL"
                " FROM reservation WHERE id = :id"
            ),
            {"id": reservation_id},
        ).one()


def _history(engine, reservation_id: int) -> list[tuple]:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT from_status, event, to_status"
                " FROM reservation_status_history WHERE reservation_id = :id"
                " ORDER BY id"
            ),
            {"id": reservation_id},
        ).all()


def test_T43_현재_상태가_맞으면_전이가_이기고_이력이_한_줄_남는다(tx, reservation_id, engine):
    repository = MySqlReservationRepository()
    with tx.write() as session:
        applied = repository.apply_event(
            session,
            reservation_id=reservation_id,
            current=ReservationStatus.PENDING,
            event=ReservationEvent.CONFIRM,
            now=NOW,
        )
    assert applied.outcome == "won"
    assert applied.restores_inventory is False  # 확정은 재고를 건드리지 않는다

    status, has_confirmed_at, has_terminated_at = _row(engine, reservation_id)
    assert status == "CONFIRMED"
    assert has_confirmed_at == 1  # 확정 시각은 표의 결과에서 파생됐다
    assert has_terminated_at == 0
    assert _history(engine, reservation_id) == [("PENDING", "CONFIRM", "CONFIRMED")]


def test_T44_현재_상태가_다르면_경합_패배이고_아무것도_안_바뀐다(tx, reservation_id, engine):
    repository = MySqlReservationRepository()
    with tx.write() as session:
        applied = repository.apply_event(
            session,
            reservation_id=reservation_id,
            current=ReservationStatus.PENDING,
            event=ReservationEvent.CANCEL,
            now=NOW,
        )
        assert applied.outcome == "won"
        assert applied.restores_inventory is True  # 취소는 복원을 일으킨다

    # DB는 이미 CANCELLED인데 호출자는 아직 PENDING으로 알고 확정을 시도한다
    with tx.write() as session:
        applied = repository.apply_event(
            session,
            reservation_id=reservation_id,
            current=ReservationStatus.PENDING,
            event=ReservationEvent.CONFIRM,
            now=NOW,
        )
        assert applied.outcome == "lost"
        assert applied.restores_inventory is False  # 진 쪽은 아무것도 하지 않는다

    status, _, has_terminated_at = _row(engine, reservation_id)
    assert status == "CANCELLED"  # 불변
    assert has_terminated_at == 1
    # 이력도 실제 전이 한 건뿐이다
    assert _history(engine, reservation_id) == [("PENDING", "CANCEL", "CANCELLED")]


def test_표_밖_조합은_UPDATE에_도달하기_전에_거부된다(tx, reservation_id, engine):
    """"표가 유일한 공급원"의 증명 — 종료 상태에서 나가는 전이를 시도한다."""
    repository = MySqlReservationRepository()
    with tx.write() as session:
        repository.apply_event(
            session,
            reservation_id=reservation_id,
            current=ReservationStatus.PENDING,
            event=ReservationEvent.EXPIRE,
            now=NOW,
        )
    # EXPIRED에서 CONFIRM — 표의 거부 칸. DB 상태와 무관하게 예외다
    with pytest.raises(InvalidStateTransitionError):
        with tx.write() as session:
            repository.apply_event(
                session,
                reservation_id=reservation_id,
                current=ReservationStatus.EXPIRED,
                event=ReservationEvent.CONFIRM,
                now=NOW,
            )
    status, _, _ = _row(engine, reservation_id)
    assert status == "EXPIRED"  # 재고 없는 확정 예약은 만들어질 수 없다


def test_멱등_조합은_UPDATE도_이력도_없이_성공한다(tx, reservation_id, engine):
    repository = MySqlReservationRepository()
    with tx.write() as session:
        repository.apply_event(
            session,
            reservation_id=reservation_id,
            current=ReservationStatus.PENDING,
            event=ReservationEvent.CANCEL,
            now=NOW,
        )
    with tx.write() as session:
        applied = repository.apply_event(
            session,
            reservation_id=reservation_id,
            current=ReservationStatus.CANCELLED,
            event=ReservationEvent.CANCEL,
            now=NOW,
        )
        assert applied.outcome == "idempotent"
        assert applied.restores_inventory is False  # 멱등은 재고를 절대 안 건드린다
    # 이력은 여전히 실제 전이 한 건뿐 — 1:1이 유지된다
    assert len(_history(engine, reservation_id)) == 1
