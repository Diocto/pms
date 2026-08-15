"""코어 두 문장의 동시성 검증 — 재고 차감(K1의 리포지토리 판)과 상태 전이(K5의 리포지토리 판).

유스케이스 없이 조건부 UPDATE 자체를 스레드로 때린다. 여기가 지면 위층의
어떤 방어도 소용없고, 여기가 버티면 락은 비용 절감 장치일 뿐이라는 3층 방어
서사가 성립한다.

공통 규칙 (스펙 4.3절):
- `threading.Barrier`로 전원을 모았다 함께 출발시킨다. Barrier 인원수와
  `max_workers`를 정확히 맞춘다 — 어긋나면 실패가 아니라 정지로 나타난다
- 예외를 종류별로 센다. 예상 못 한 예외가 하나라도 있으면 실패다
- 결과 수가 아니라 DB 최종 상태를 직접 조회한다
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager
from app.inventory.domain.errors import InsufficientInventoryError
from app.inventory.infrastructure.persistence import MySqlInventoryRepository
from app.reservation.domain.enums import ReservationStatus
from app.reservation.infrastructure.persistence import MySqlReservationRepository

NOW = datetime(2026, 8, 15, 12, 0, 0)
ROOM_TYPE_ID = 902
STAY_DATE = date(2026, 9, 10)

pytestmark = pytest.mark.concurrency


@pytest.fixture(scope="module")
def engine(database_url):
    # 스레드 수만큼 커넥션이 필요하다. 풀이 작으면 경합이 커넥션 대기로
    # 흡수되어 DB 행 경합이 약해진다
    engine = create_engine(database_url, pool_size=30, max_overflow=80)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (902, '테스트 호텔 902', '테스트 주소', NOW(6))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price, created_at)"
                " VALUES (:id, 902, '테스트 타입 902', 2, 10, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID},
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reservation_status_history"))
        conn.execute(
            text("DELETE FROM reservation WHERE user_id LIKE 'test-conc-%'")
        )
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM hotel WHERE id = 902"))
    engine.dispose()


def test_잔여_10에_100스레드가_동시_차감하면_성공은_정확히_10이다(engine):
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_daily_inventory"
                " (room_type_id, stay_date, total_quantity, remaining,"
                "  created_at, updated_at)"
                " VALUES (:id, :d, 10, 10, NOW(6), NOW(6))"
            ),
            {"id": ROOM_TYPE_ID, "d": STAY_DATE},
        )

    tx = TransactionManager(sessionmaker(bind=engine))
    repository = MySqlInventoryRepository()
    threads = 100
    barrier = threading.Barrier(threads)
    success = 0
    insufficient = 0
    unexpected: list[Exception] = []
    count_lock = threading.Lock()

    def attempt() -> None:
        nonlocal success, insufficient
        barrier.wait()  # 전원이 모인 뒤 함께 출발한다
        try:
            with tx.write() as session:
                repository.deduct(
                    session,
                    room_type_id=ROOM_TYPE_ID,
                    stay_dates=[STAY_DATE],
                    room_count=1,
                    now=NOW,
                )
            with count_lock:
                success += 1
        except InsufficientInventoryError:
            with count_lock:
                insufficient += 1
        except Exception as error:  # noqa: BLE001 — 예상 못 한 것을 세는 자리다
            with count_lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:  # Barrier 인원수와 동일
        for _ in range(threads):
            pool.submit(attempt)

    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert success == 10
    assert insufficient == 90  # 경합이 실제로 일어났다는 증거이기도 하다

    with engine.connect() as conn:
        remaining = conn.execute(
            text(
                "SELECT remaining FROM room_daily_inventory"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": ROOM_TYPE_ID, "d": STAY_DATE},
        ).scalar_one()
    assert remaining == 0


def test_같은_예약에_50스레드가_동시_전이하면_승자는_정확히_1이다(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reservation"
                " (confirmation_code, user_id, room_type_id, check_in, check_out,"
                "  room_count, guest_count, price_per_night, total_price, status,"
                "  idempotency_key, expires_at, created_at, updated_at)"
                " VALUES ('CONC-0001', 'test-conc-01', 1, '2026-09-01',"
                "  '2026-09-04', 1, 2, 150000, 450000, 'PENDING',"
                "  'idem-conc-0001', NOW(6), NOW(6), NOW(6))"
            )
        )
        reservation_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar_one()

    tx = TransactionManager(sessionmaker(bind=engine))
    repository = MySqlReservationRepository()
    threads = 50
    barrier = threading.Barrier(threads)
    wins: list[str] = []
    unexpected: list[Exception] = []
    count_lock = threading.Lock()

    def attempt(index: int) -> None:
        # 절반은 확정, 절반은 취소 — 서로 다른 목표 상태로 같은 행을 노린다 (C4)
        next_status = (
            ReservationStatus.CONFIRMED if index % 2 == 0 else ReservationStatus.CANCELLED
        )
        barrier.wait()
        try:
            with tx.write() as session:
                won = repository.transition(
                    session,
                    reservation_id=reservation_id,
                    expected=ReservationStatus.PENDING,
                    next_status=next_status,
                    now=NOW,
                )
            if won:
                with count_lock:
                    wins.append(next_status.value)
        except Exception as error:  # noqa: BLE001
            with count_lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for index in range(threads):
            pool.submit(attempt, index)

    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert len(wins) == 1, f"승자가 하나여야 한다: {wins}"

    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM reservation WHERE id = :id"),
            {"id": reservation_id},
        ).scalar_one()
    assert status == wins[0]  # 최종 상태는 승자의 목표 상태 하나뿐이다
