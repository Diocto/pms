"""경합 패배(lost)의 유스케이스별 처리 — 스텁으로 결정적으로 재현한다.

동시성 테스트(K5·K6)는 타이밍에 따라 어느 쪽이 이기는지가 갈려 특정 분기를
확정적으로 밟지 못한다. 여기서는 리포지토리 스텁으로 lost를 강제해
스펙 행(취소·체크인 409 / 확정 보상+409 / 거절+패배 200)을 하나씩 고정한다.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest

from app.common.clock import FixedClock
from app.inventory.domain.models import Money, RoomType
from app.reservation.application.usecases.transition_reservation import (
    CancelReservationUseCase,
    CheckInOutUseCase,
    ConfirmReservationUseCase,
)
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.errors import InvalidStateTransitionError
from app.reservation.domain.models import GuestCount, Reservation, StayPeriod
from app.reservation.domain.repositories import EventApplication
from app.reservation.infrastructure.payment import FakePaymentAdapter

NOW = datetime(2026, 9, 1, 12, 0, 0)
TODAY = date(2026, 9, 1)

ROOM_TYPE = RoomType(
    id=1, hotel_id=1, name="스탠다드", capacity=2, total_quantity=100,
    base_price=100000, created_at=NOW,
)


class FakeTx:
    @contextmanager
    def write(self):
        yield None  # 스텁 리포지토리는 세션을 쓰지 않는다

    @contextmanager
    def read(self):
        yield None


class StubRepository:
    """apply_event가 정해진 outcome을 돌려주는 스텁 — lost를 강제한다."""

    def __init__(self, reservation: Reservation, outcome: str) -> None:
        self._reservation = reservation
        self._outcome = outcome
        self.applied: list[tuple[ReservationStatus, ReservationEvent]] = []

    def find_by_code(self, session, code):
        return self._reservation

    def apply_event(self, session, *, reservation_id, current, event, now):
        self.applied.append((current, event))
        return EventApplication(outcome=self._outcome, restores_inventory=False)


class StubInventory:
    def restore(self, session, **kwargs):  # noqa: ANN003
        pytest.fail("lost 경로에서 복원이 불리면 안 된다")

    def deduct(self, session, **kwargs):  # noqa: ANN003
        pytest.fail("이 시나리오에서 차감은 없다")


def _reservation(status: ReservationStatus) -> Reservation:
    reservation = Reservation.create(
        user_id="u",
        idempotency_key="k",
        room_type=ROOM_TYPE,
        period=StayPeriod(check_in=TODAY, check_out=TODAY + timedelta(days=2)),
        room_count=1,
        guest_count=GuestCount(value=2),
        price_per_night=Money(amount=100000),
        confirmation_code="RACE-0001",
        today=TODAY,
        now=NOW,
        hold_minutes=10,
    )
    reservation.id = 1  # 스텁 세계의 id
    reservation.status = status.value  # 테스트 셋업 한정의 표 우회
    return reservation


def _deps(repository) -> dict:
    return dict(
        tx=FakeTx(),
        inventory_repository=StubInventory(),
        reservation_repository=repository,
        clock=FixedClock(NOW),
        release_hooks=[],
    )


def test_취소가_경합에서_지면_200이_아니라_409다():
    repository = StubRepository(_reservation(ReservationStatus.PENDING), "lost")
    usecase = CancelReservationUseCase(**_deps(repository))
    with pytest.raises(InvalidStateTransitionError):
        usecase.execute(confirmation_code="RACE-0001", user_id="u")
    # 정당화한 상태(PENDING)가 그대로 UPDATE 조건에 걸렸다
    assert repository.applied == [(ReservationStatus.PENDING, ReservationEvent.CANCEL)]


def test_체크인이_경합에서_지면_409다():
    repository = StubRepository(_reservation(ReservationStatus.CONFIRMED), "lost")
    usecase = CheckInOutUseCase(**_deps(repository))
    with pytest.raises(InvalidStateTransitionError):
        usecase.check_in(confirmation_code="RACE-0001")


def test_T62_결제_승인_후_경합에서_지면_환불하고_409다():
    """스펙 2.3 실패 표 6행 — "결제 취소(환불)를 호출해 보상한다".

    재조회 상태로 판정하던 옛 구현은 이 보상 경로에 사실상 도달하지 못했다
    (4회차 리뷰 심각). 지금은 승인 후 won이 아닌 모든 경합 패배가 이 분기
    하나로 수렴한다 — 이중 확정 창의 패배자도 자기 결제를 되돌린다.
    """
    repository = StubRepository(_reservation(ReservationStatus.PENDING), "lost")
    payment = FakePaymentAdapter(decline_rate=0.0)
    usecase = ConfirmReservationUseCase(payment=payment, **_deps(repository))
    with pytest.raises(InvalidStateTransitionError):
        usecase.execute(confirmation_code="RACE-0001")
    assert len(payment.charged) == 1
    assert len(payment.refunded) == 1        # 내 결제를 내가 되돌렸다
    # 결제를 정당화한 PENDING이 UPDATE 조건이다 — 재조회 상태가 아니다
    assert repository.applied == [(ReservationStatus.PENDING, ReservationEvent.CONFIRM)]


def test_결제_거절_후_경합에서_지면_승자가_정리했으므로_200이다():
    repository = StubRepository(_reservation(ReservationStatus.PENDING), "lost")
    payment = FakePaymentAdapter(decline_rate=1.0)
    usecase = ConfirmReservationUseCase(payment=payment, **_deps(repository))
    result = usecase.execute(confirmation_code="RACE-0001")
    assert result.failure_reason == "PAYMENT_DECLINED"
    assert payment.refunded == []            # 거절 건은 되돌릴 결제가 없다
