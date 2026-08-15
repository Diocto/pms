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
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
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
        conn.execute(
            text(
                "DELETE FROM reservation_status_history WHERE reservation_id IN"
                " (SELECT id FROM reservation WHERE user_id LIKE 'test-conc-%')"
            )
        )
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
        try:
            barrier.wait()  # 전원이 모인 뒤 함께 출발. 배리어 파손도 예외로 계측된다
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
        futures = [pool.submit(attempt) for _ in range(threads)]
    for future in futures:
        future.result()  # submit 계층에서 사라지는 예외가 없게 수거한다

    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert success == 10
    assert insufficient == 90  # 경합이 실제로 일어났다는 증거이기도 하다
    assert success + insufficient == threads  # 회계가 닫힌다 — 전원이 시도했다

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
    losses = 0
    unexpected: list[Exception] = []
    count_lock = threading.Lock()

    def attempt(index: int) -> None:
        nonlocal losses
        # 절반은 확정, 절반은 취소 — 서로 다른 이벤트로 같은 행을 노린다 (C4)
        event = ReservationEvent.CONFIRM if index % 2 == 0 else ReservationEvent.CANCEL
        try:
            barrier.wait()
            with tx.write() as session:
                applied = repository.apply_event(
                    session,
                    reservation_id=reservation_id,
                    current=ReservationStatus.PENDING,
                    event=event,
                    now=NOW,
                )
            with count_lock:
                if applied.outcome == "won":
                    wins.append(
                        "CONFIRMED" if event is ReservationEvent.CONFIRM else "CANCELLED"
                    )
                else:
                    losses += 1
        except Exception as error:  # noqa: BLE001
            with count_lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(attempt, index) for index in range(threads)]
    for future in futures:
        future.result()

    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert len(wins) == 1, f"승자가 하나여야 한다: {wins}"
    assert losses == threads - 1  # 회계가 닫힌다 — 나머지 전원이 패배를 확인했다

    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM reservation WHERE id = :id"),
            {"id": reservation_id},
        ).scalar_one()
    assert status == wins[0]  # 최종 상태는 승자의 목표 상태 하나뿐이다


def test_겹치는_날짜를_역순으로_넣어도_데드락이_나지_않는다(engine):
    """K8의 리포지토리 판 — `sorted()`가 이번 회차 유일의 순서 방어선이다.

    이 테스트가 없으면 `sorted()`를 지워도 전부 초록이다(리뷰 지적).
    두 그룹이 같은 날짜 쌍을 **의도적으로 반대 순서**로 넘긴다. 정렬이
    없으면 A가 9/11 행을 쥐고 9/10을 기다리는 사이 B가 9/10을 쥐고
    9/11을 기다려 InnoDB 데드락(1213)이 난다.
    """
    date_a, date_b = date(2026, 9, 10), date(2026, 9, 11)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        for stay_date in (date_a, date_b):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining,"
                    "  created_at, updated_at)"
                    " VALUES (:id, :d, 10, 10, NOW(6), NOW(6))"
                    " ON DUPLICATE KEY UPDATE remaining = 10, total_quantity = 10"
                ),
                {"id": ROOM_TYPE_ID, "d": stay_date},
            )
        # 잔여를 넉넉히 — 부족이 아니라 순서만 시험한다
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET total_quantity = 100, remaining = 100"
                " WHERE room_type_id = :id"
            ),
            {"id": ROOM_TYPE_ID},
        )

    tx = TransactionManager(sessionmaker(bind=engine))
    repository = MySqlInventoryRepository()
    threads = 20
    barrier = threading.Barrier(threads)
    success = 0
    deadlocks = 0
    unexpected: list[Exception] = []
    count_lock = threading.Lock()

    def attempt(index: int) -> None:
        nonlocal success, deadlocks
        # 절반은 [뒤, 앞], 절반은 [앞, 뒤] — 정렬이 없으면 서로 물린다
        stay_dates = [date_b, date_a] if index % 2 == 0 else [date_a, date_b]
        try:
            barrier.wait()
            with tx.write() as session:
                repository.deduct(
                    session,
                    room_type_id=ROOM_TYPE_ID,
                    stay_dates=stay_dates,
                    room_count=1,
                    now=NOW,
                )
            with count_lock:
                success += 1
        except Exception as error:  # noqa: BLE001
            from sqlalchemy.exc import OperationalError

            is_deadlock = (
                isinstance(error, OperationalError)
                and getattr(error.orig, "args", [None])[0] == 1213
            )
            with count_lock:
                if is_deadlock:
                    deadlocks += 1
                else:
                    unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(attempt, index) for index in range(threads)]
    for future in futures:
        future.result()

    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert deadlocks == 0, f"데드락 {deadlocks}건 — 순서 방어선이 깨졌다"
    assert success == threads


def test_동시_복원은_상한_감지가_정확히_하나를_거른다(engine):
    """K6의 리포지토리 판 — 복원 상한 조건이 경합 타이밍에서 작동하는가.

    잔여 9/총량 10에서 두 스레드가 +1 복원을 동시 시도하면, 조건
    `remaining + 1 <= total_quantity`를 통과하는 것은 하나뿐이다.
    다른 하나는 이중 복원 감지(InventoryRestoreMismatchError)를 받아야 한다.
    """
    from app.inventory.domain.errors import InventoryRestoreMismatchError

    stay_date = date(2026, 9, 20)
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
                " VALUES (:id, :d, 10, 9, NOW(6), NOW(6))"
            ),
            {"id": ROOM_TYPE_ID, "d": stay_date},
        )

    tx = TransactionManager(sessionmaker(bind=engine))
    repository = MySqlInventoryRepository()
    threads = 2
    barrier = threading.Barrier(threads)
    success = 0
    detected = 0
    unexpected: list[Exception] = []
    count_lock = threading.Lock()

    def attempt() -> None:
        nonlocal success, detected
        try:
            barrier.wait()
            with tx.write() as session:
                repository.restore(
                    session,
                    room_type_id=ROOM_TYPE_ID,
                    stay_dates=[stay_date],
                    room_count=1,
                    now=NOW,
                )
            with count_lock:
                success += 1
        except InventoryRestoreMismatchError:
            with count_lock:
                detected += 1
        except Exception as error:  # noqa: BLE001
            with count_lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(attempt) for _ in range(threads)]
    for future in futures:
        future.result()

    assert unexpected == []
    assert success == 1 and detected == 1  # 정확히 하나만 복원, 하나는 감지

    with engine.connect() as conn:
        remaining = conn.execute(
            text(
                "SELECT remaining FROM room_daily_inventory"
                " WHERE room_type_id = :id AND stay_date = :d"
            ),
            {"id": ROOM_TYPE_ID, "d": stay_date},
        ).scalar_one()
    assert remaining == 10  # 총량을 넘지 않았다
