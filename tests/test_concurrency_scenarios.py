"""동시성 시나리오 K1~K10 (스펙 4.3절) — 이 프로젝트가 증명하려는 것 전부.

유스케이스 계층을 실제 MySQL·Redis 위에서 스레드로 때린다. 공통 규칙:
Barrier 인원 = max_workers, 예외 종류별 카운트(예상 못 한 것 0건),
DB 최종 상태 직접 조회, 경합이 실제로 일어났다는 증거 단언, 회계 닫기.

시드에 의존하지 않는다 — 전용 객실타입(905)과 재고를 시나리오마다 만든다.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
import redis as redis_library
from sqlalchemy import create_engine, text

from app.common.errors import DomainError
from app.containers import AppContainer
from app.inventory.domain.errors import InsufficientInventoryError
from app.reservation.application.commands import CreateReservationCommand, OrderLine
from app.reservation.application.errors import (
    LockAcquisitionError,
    RequestInProgressError,
)
from app.reservation.domain.models import GuestCount, StayPeriod

pytestmark = pytest.mark.concurrency

ROOM_TYPE_ID = 905
D1 = date(2026, 9, 20)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url, pool_size=20, max_overflow=60)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (905, '테스트 호텔 905', '주소', NOW(6))"
                " ON DUPLICATE KEY UPDATE name = name"
            )
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price, created_at)"
                " VALUES (:id, 905, '경합 타입 905', 4, 100, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID},
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reservation_status_history WHERE reservation_id IN (SELECT id FROM reservation WHERE room_type_id = :id)"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM hotel WHERE id = 905"))
    engine.dispose()


def _make_container(database_url, redis_url, engine, *, lock_enabled=True):
    os.environ["PMS_DATABASE_URL"] = database_url
    os.environ["PMS_REDIS_URL"] = redis_url
    os.environ["PMS_LOCK_ENABLED"] = "true" if lock_enabled else "false"
    # 락 대기 상한을 넉넉히 — K 시나리오는 상한이 아니라 정확성을 잰다.
    # 상한 자체의 검증은 test_lock.py 몫이다
    os.environ["PMS_LOCK_WAIT_MILLIS"] = "10000"
    try:
        container = AppContainer()
        container.settings()  # ← env 창이 닫히기 전에 설정을 읽어 고정한다
        from dependency_injector import providers

        container.engine.override(providers.Object(engine))  # 넉넉한 풀 공유
        return container
    finally:
        for name in ("PMS_LOCK_ENABLED", "PMS_LOCK_WAIT_MILLIS"):
            os.environ.pop(name, None)


@pytest.fixture()
def container(database_url, redis_url, engine):
    _reset(engine, redis_url)
    return _make_container(database_url, redis_url, engine)


def _reset(engine, redis_url, *, remaining=10, days=7):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reservation_status_history WHERE reservation_id IN (SELECT id FROM reservation WHERE room_type_id = :id)"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM reservation WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        conn.execute(text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"), {"id": ROOM_TYPE_ID})
        for offset in range(days):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining, created_at, updated_at)"
                    " VALUES (:id, :d, 100, :r, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": D1 + timedelta(days=offset), "r": remaining},
            )
    client = redis_library.Redis.from_url(redis_url)
    client.flushdb()
    client.close()


def _command(user: str, key: str, *, check_in=D1, nights=1, room_count=1,
             guest_count=1) -> CreateReservationCommand:
    return CreateReservationCommand(
        user_id=user,
        idempotency_key=key,
        line=OrderLine(
            room_type_id=ROOM_TYPE_ID,
            stay_period=StayPeriod(
                check_in=check_in, check_out=check_in + timedelta(days=nights)
            ),
            room_count=room_count,
            guest_count=GuestCount(value=guest_count),
        ),
    )


def _run(threads: int, task) -> tuple[list, list, list]:
    """Barrier 동시 출발. (성공 결과, 도메인 실패, 예상 못 한 예외)를 돌려준다."""
    barrier = threading.Barrier(threads)
    successes, domain_failures, unexpected = [], [], []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            barrier.wait()
            outcome = task(index)
            with lock:
                successes.append(outcome)
        except DomainError as error:
            with lock:
                domain_failures.append(error)
        except Exception as error:  # noqa: BLE001
            with lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(attempt, index) for index in range(threads)]
    for future in futures:
        future.result()
    return successes, domain_failures, unexpected


def _remaining(engine, stay_date: date) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT remaining FROM room_daily_inventory WHERE room_type_id = :id AND stay_date = :d"),
            {"id": ROOM_TYPE_ID, "d": stay_date},
        ).scalar_one()


def _reservation_count(engine, status: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM reservation WHERE room_type_id = :id"
    if status:
        query += f" AND status = '{status}'"
    with engine.connect() as conn:
        return conn.execute(text(query), {"id": ROOM_TYPE_ID}).scalar_one()


# ── K1·K2: 초과 판매 ────────────────────────────────────────────────

def _oversell_scenario(container, engine):
    usecase = container.reservation.create_reservation()
    successes, failures, unexpected = _run(
        100, lambda index: usecase.execute(_command(f"user-{index}", f"k1-{index}"))
    )
    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert len(successes) == 10          # 잔여 10 — 성공 정확히 10
    assert len(failures) == 90           # 회계가 닫힌다. 경합의 증거이기도 하다
    assert all(
        isinstance(f, (InsufficientInventoryError, LockAcquisitionError))
        for f in failures
    )
    assert _remaining(engine, D1) == 0
    assert _reservation_count(engine) == 10  # 응답이 아니라 DB 행을 직접 센다


def test_K1_잔여_10에_100명이_동시_예약하면_성공은_정확히_10이다(container, engine):
    """예약 생성 동시성(K1) — 서로 다른 100명이 잔여 10인 같은 날짜에 동시에
    예약을 만들면 성공 정확히 10, 실패 90(재고 부족 또는 락 획득 실패)이다.
    잔여는 0이 되고 DB 예약 행도 정확히 10건 — 3층 방어 전체가 켜진 기본형."""
    _oversell_scenario(container, engine)


def test_K2_분산락을_꺼도_결과가_같다__2층_방어_단독_성립_증명(
    database_url, redis_url, engine
):
    """예약 생성 동시성(K2) — 분산락을 끄고(NoOpLockAdapter) 잔여 10에 100요청을
    동시에 쏴도 성공이 정확히 10이다. 조건부 UPDATE(2층 방어)만으로 초과 판매를
    막는 증명 — 락은 정확성이 아니라 비용 절감 장치라는 서사의 근거다."""
    _reset(engine, redis_url)
    container = _make_container(database_url, redis_url, engine, lock_enabled=False)
    assert type(container.reservation.lock()).__name__ == "NoOpLockAdapter"  # 전제 확인
    _oversell_scenario(container, engine)


# ── K3·K4: 멱등성 ───────────────────────────────────────────────────

def test_K3_같은_멱등_키_50_동시_요청은_예약_1건이다(container, engine):
    """멱등성 동시성(K3) — 같은 사용자가 같은 멱등 키로 50요청을 동시에 보내면
    최초 처리는 정확히 1건, 겹친 요청은 처리 중 409(RequestInProgressError)를
    받는다. 예약은 1건, 재고는 한 번만 깎여 잔여 9다. 실패 0건이면 요청이
    안 겹친 것이므로 경합 증거(실패 1건 이상)도 함께 단언한다."""
    usecase = container.reservation.create_reservation()
    successes, failures, unexpected = _run(
        50, lambda index: usecase.execute(_command("same-user", "same-key"))
    )
    assert unexpected == []
    assert all(isinstance(f, RequestInProgressError) for f in failures)
    assert len(successes) + len(failures) == 50   # 회계가 닫힌다
    # 경합 증거 — 실패 0건이면 요청이 안 겹친 것이고 그런 통과는 무의미하다
    assert len(failures) >= 1
    assert sum(1 for r in successes if not r.replayed) == 1  # 최초는 정확히 하나
    assert _reservation_count(engine) == 1   # 예약은 정확히 1건
    assert _remaining(engine, D1) == 9       # 한 번만 깎였다


def test_K4_Redis_멱등을_무력화해도_DB_UK가_1건을_지킨다(container, engine):
    """멱등성 최후 방어(K4) — Redis 멱등을 무력화해 같은 키 50요청이 전부 최초로
    통과해도 DB 유니크 제약이 예약을 1건으로 지킨다(D9). 뚫린 49건은 500이
    아니라 기존 예약 재생(replayed)으로 응답받고(T54), 잔여는 9 그대로다."""
    class DisabledIdempotency:
        """Redis 장애의 재현 — 전부 최초 요청으로 통과시킨다."""

        def claim(self, *, user_id, key, ttl_seconds):
            from app.reservation.application.ports import IdempotencyClaim

            return IdempotencyClaim(outcome="acquired")

        def store(self, **kwargs): ...
        def store_failure(self, **kwargs): ...
        def release(self, **kwargs): ...

    container.reservation.idempotency.override(DisabledIdempotency())
    try:
        usecase = container.reservation.create_reservation()
        successes, failures, unexpected = _run(
            50, lambda index: usecase.execute(_command("same-user", "same-key"))
        )
    finally:
        container.reservation.idempotency.reset_override()
    assert unexpected == []
    assert _reservation_count(engine) == 1   # UK가 최후 방어선이다 (D9)
    assert _remaining(engine, D1) == 9
    # 뚫린 요청들은 500이 아니라 기존 예약을 돌려받았다 (T54)
    assert len(successes) == 50
    assert sum(1 for result in successes if result.replayed) == 49


# ── K5·K6: 전이 경합과 이중 복원 ─────────────────────────────────────

def _create_pending(container, *, nights=3, key="pending-1") -> str:
    result = container.reservation.create_reservation().execute(
        _command("transition-user", key, nights=nights)
    )
    return result.confirmation_code


def test_K5_확정과_취소가_동시에_오면_최종_상태는_하나다(container, engine):
    """전이 경합(확정 vs 취소, K5) — 같은 PENDING 예약에 확정 25·취소 25가
    동시에 오면 최종 상태는 CONFIRMED나 CANCELLED 중 하나다. 확정 승리 후
    취소가 뒤따르는 순서도 합법이므로 불변식은 "복원 동반 전이 최대 1회"로
    단언하고, 잔여도 상태와 정합해야 한다(3박 전체가 확정이면 9, 취소면 10)."""
    code = _create_pending(container)
    confirm = container.reservation.confirm_reservation()
    cancel = container.reservation.cancel_reservation()

    def task(index: int):
        if index % 2 == 0:
            return confirm.execute(confirmation_code=code, user_id="transition-user")
        return cancel.execute(confirmation_code=code, user_id="transition-user")

    successes, failures, unexpected = _run(50, task)
    assert unexpected == []

    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM reservation WHERE confirmation_code = :c"),
            {"c": code},
        ).scalar_one()
        rows = conn.execute(
            text(
                "SELECT h.from_status, h.event, h.to_status"
                " FROM reservation_status_history h"
                " JOIN reservation r ON r.id = h.reservation_id"
                " WHERE r.confirmation_code = :c ORDER BY h.id"
            ),
            {"c": code},
        ).all()
    # 불변식으로 단언한다 (리뷰 지적) — "이력 1줄"은 시스템 불변식이 아니다.
    # 확정이 먼저 이기고 취소가 뒤따르는 순서(CONFIRMED→CANCELLED)는 합법이라
    # 이력 2줄이 정당하다. 불변은 "복원을 동반한 전이는 최대 1회"다
    restoring = [r for r in rows if r[2] in ("CANCELLED", "EXPIRED")]
    assert len(restoring) <= 1
    assert status in ("CONFIRMED", "CANCELLED")
    if status == "CANCELLED":
        assert len(restoring) == 1           # 취소됐으면 복원 전이가 정확히 하나
        expected_remaining = 10
    else:
        assert restoring == []               # 확정 상태면 복원이 없었어야 한다
        assert rows == [("PENDING", "CONFIRM", "CONFIRMED")]
        expected_remaining = 9
    for offset in range(3):
        assert _remaining(engine, D1 + timedelta(days=offset)) == expected_remaining


def test_K6_취소와_만료가_겹쳐도_복원은_정확히_한_번이다(container, engine):
    """전이 경합(취소 vs 만료, K6) — 만료 시각이 지난 PENDING 하나에 취소 50과
    만료 배치 10이 동시에 달려들어도 재고 복원은 정확히 한 번이다. 3박 전체의
    잔여가 10으로 돌아오고(이중 복원이면 11), 복원 전이 이력도 정확히 1줄이다."""
    code = _create_pending(container, key="expired-1")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE reservation SET expires_at = NOW(6) - INTERVAL 1 MINUTE WHERE confirmation_code = :c"),
            {"c": code},
        )
    cancel = container.reservation.cancel_reservation()
    expire = container.reservation.expire_reservations()

    def task(index: int):
        if index < 50:
            return cancel.execute(confirmation_code=code, user_id="transition-user")
        return expire.execute()

    successes, failures, unexpected = _run(60, task)
    assert unexpected == []
    for offset in range(3):
        # 10 - 1(생성 차감) + 1(복원 정확히 한 번) = 10. 이중 복원이면 11이다 —
        # 총량이 100이라 CHECK 상한에 안 걸리므로 이 단언이 직접 잡는다
        assert _remaining(engine, D1 + timedelta(days=offset)) == 10
    # 이력 줄 수도 함께 센다 (4.3절 공통 규칙) — "두 번 깎고 두 번 되돌린"
    # 회귀는 잔여가 10으로 돌아와 위 단언을 통과하기 때문이다
    with engine.connect() as conn:
        restoring = conn.execute(
            text(
                "SELECT COUNT(*) FROM reservation_status_history h"
                " JOIN reservation r ON r.id = h.reservation_id"
                " WHERE r.confirmation_code = :c"
                "   AND h.to_status IN ('CANCELLED', 'EXPIRED')"
            ),
            {"c": code},
        ).scalar_one()
    assert restoring == 1


def test_K10_취소_이력은_정확히_한_줄이다(container, engine):
    """전이 경합(취소 vs 취소, K10) — 확정된 예약 하나에 취소 50이 동시에 와도
    CANCELLED 전이 이력은 정확히 1줄이다. 두 번 취소하고 두 번 복원하는 회귀는
    잔여만 보면 통과하므로 이력 줄 수를 직접 센다."""
    code = _create_pending(container, key="confirmed-1")
    container.reservation.confirm_reservation().execute(confirmation_code=code, user_id="transition-user")
    cancel = container.reservation.cancel_reservation()
    successes, failures, unexpected = _run(
        50, lambda i: cancel.execute(confirmation_code=code, user_id="transition-user")
    )
    assert unexpected == []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT COUNT(*) FROM reservation_status_history h"
                " JOIN reservation r ON r.id = h.reservation_id"
                " WHERE r.confirmation_code = :c AND h.to_status = 'CANCELLED'"
            ),
            {"c": code},
        ).scalar_one()
    assert rows == 1                          # 잔여만 보면 놓치는 것을 이력이 잡는다


# ── K7·K9: 다일·다실 부분 소진 ──────────────────────────────────────

def test_K7_가운데_날짜만_잔여_1이면_성공은_정확히_1이고_부분_차감이_없다(
    container, engine
):
    """다일 예약 동시성(K7) — 3박 요청 100건이 경합하는데 가운데 날짜만 잔여
    1이면 성공은 정확히 1이다. 실패한 99건이 1·3일차를 깎아두지 않아야 한다 —
    1·3일차 잔여 99, 2일차 0. 유령 점유(부분 차감) 없음의 증명."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE room_daily_inventory SET remaining = 100 WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(
            text("UPDATE room_daily_inventory SET remaining = 1 WHERE room_type_id = :id AND stay_date = :d"),
            {"id": ROOM_TYPE_ID, "d": D1 + timedelta(days=1)},
        )
    usecase = container.reservation.create_reservation()
    successes, failures, unexpected = _run(
        100, lambda index: usecase.execute(_command(f"u{index}", f"k7-{index}", nights=3))
    )
    assert unexpected == []
    assert len(successes) == 1
    # 실패 99건이 1·3일차를 깎아두지 않았다 — 유령 점유 없음
    assert _remaining(engine, D1) == 99
    assert _remaining(engine, D1 + timedelta(days=1)) == 0
    assert _remaining(engine, D1 + timedelta(days=2)) == 99


def test_K9_잔여_10에_3실씩_요청하면_성공은_정확히_3이고_잔여_1이_남는다(
    container, engine
):
    """다실 예약 동시성(K9) — 잔여 10에 3실짜리 요청 100건이 경합하면 성공은
    정확히 3건(3실 × 3건 = 9실)이고 잔여 1이 남는다. room_count 곱셈이 차감
    조건에 정확히 반영되는지, 부분 소진이 깔끔히 남는지를 본다."""
    usecase = container.reservation.create_reservation()
    successes, failures, unexpected = _run(
        100,
        lambda index: usecase.execute(
            _command(f"u{index}", f"k9-{index}", room_count=3, guest_count=4)
        ),
    )
    assert unexpected == []
    assert len(successes) == 3               # 3실 × 3건 = 9
    assert _remaining(engine, D1) == 1       # 부분 소진 — 1이 남는다


# ── K8: 데드락 ──────────────────────────────────────────────────────

def test_K8_겹치는_기간을_반대_순서로_요청해도_데드락이_없다(container, engine):
    """데드락(K8) — 절반은 9/20~23, 절반은 9/22~25로 9/22 행이 겹치는 100요청을
    동시에 보낸다. 재고가 넉넉하므로(잔여 100) 전원 성공(100)이어야 하고,
    데드락(1213)은 unexpected로 잡혀 0건이어야 한다. 날짜 정렬 접근의 증명."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE room_daily_inventory SET remaining = 100 WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
    usecase = container.reservation.create_reservation()

    def task(index: int):
        # 절반은 9/20~9/23, 절반은 9/22~9/25 — 9/22가 겹친다
        check_in = D1 if index % 2 == 0 else D1 + timedelta(days=2)
        return usecase.execute(_command(f"u{index}", f"k8-{index}", check_in=check_in, nights=3))

    successes, failures, unexpected = _run(100, task)
    # 데드락(1213)은 OperationalError라 unexpected로 잡힌다 — 0건이어야 한다
    assert unexpected == [], f"데드락 의심: {unexpected[:3]}"
    assert len(successes) == 100             # 재고가 충분하니 전원 성공


def test_K2b_락을_꺼도_K8_데드락이_없다__행_접근_순서_증명(
    database_url, redis_url, engine
):
    """데드락(K2b, 락 없이 K8) — 분산락을 끄면 방어선이 InnoDB 행 락뿐이다.
    겹치는 기간 60요청을 동시에 보내 데드락 0, 전원 성공(60)을 확인해
    deduct의 정렬이 실제 방어선임을 유스케이스 경로 전체로 증명한다
    (D10의 두 번째 조건)."""
    _reset(engine, redis_url, remaining=100)
    container = _make_container(database_url, redis_url, engine, lock_enabled=False)
    usecase = container.reservation.create_reservation()

    def task(index: int):
        check_in = D1 if index % 2 == 0 else D1 + timedelta(days=2)
        return usecase.execute(_command(f"u{index}", f"k2b-{index}", check_in=check_in, nights=3))

    successes, failures, unexpected = _run(60, task)
    assert unexpected == [], f"데드락 의심: {unexpected[:3]}"
    assert len(successes) == 60
