"""상태 전이 유스케이스들 — 확정·취소·체크인·체크아웃 (스펙 2.3·2.4·2.6절).

넷의 뼈대가 같다: 조회 → 표 판정(resolve) → [시간창 검증] → apply_event →
[복원 + 반납 훅]. 다른 것은 이벤트와 곁가지뿐이라 한 파일에 둔다.

**복원과 반납 훅은 전이에서 이긴 쪽만 실행한다** — apply_event가 rowcount 1을
받은 트랜잭션 안에서만 부른다. 이것이 이중 복원(C6)을 막는 유일한 논리다 (3.2절).
"""

import logging
from datetime import datetime

from app.common.clock import Clock
from app.common.db import TransactionManager
from app.inventory.domain.repositories import InventoryRepository
from app.reservation.application.commands import ReservationResult
from app.reservation.application.ports import PaymentPort, ReservationReleaseHook
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.errors import ReservationNotFoundError
from app.reservation.domain.models import Reservation, StayPeriod
from app.reservation.domain.transitions import resolve
from app.reservation.infrastructure.persistence import MySqlReservationRepository

logger = logging.getLogger(__name__)


class _TransitionBase:
    def __init__(
        self,
        *,
        tx: TransactionManager,
        inventory_repository: InventoryRepository,
        reservation_repository: MySqlReservationRepository,
        clock: Clock,
        release_hooks: list[ReservationReleaseHook],
    ) -> None:
        self._tx = tx
        self._inventory = inventory_repository
        self._reservations = reservation_repository
        self._clock = clock
        self._release_hooks = release_hooks

    def _now(self) -> datetime:
        return self._clock.now().replace(tzinfo=None)  # DATETIME 경계 — naive KST

    def _load_by_code(self, session, code: str) -> Reservation:
        reservation = self._reservations.find_by_code(session, code)
        if reservation is None:
            raise ReservationNotFoundError("예약을 찾을 수 없습니다")
        return reservation

    def _apply_and_settle(
        self, session, reservation: Reservation, event: ReservationEvent, now: datetime
    ) -> str:
        """전이를 적용하고, 이긴 쪽만 복원·반납 훅을 태운다. outcome을 돌려준다."""
        current = ReservationStatus(reservation.status)
        applied = self._reservations.apply_event(
            session,
            reservation_id=reservation.id,
            current=current,
            event=event,
            now=now,
        )
        if applied.outcome == "won" and applied.restores_inventory:
            period = StayPeriod(
                check_in=reservation.check_in, check_out=reservation.check_out
            )
            self._inventory.restore(
                session,
                room_type_id=reservation.room_type_id,
                stay_dates=period.occupied_dates(),
                room_count=reservation.room_count,
                now=now,
            )
            for hook in self._release_hooks:
                # 정확히 한 번 — rowcount 1을 받은 이 트랜잭션에서만 (3.6절)
                hook.on_released(session, reservation.id, current, event)
        return applied.outcome

    def _result(self, session, code: str, **updates) -> ReservationResult:
        reservation = self._load_by_code(session, code)
        result = ReservationResult.model_validate(reservation)
        return result.model_copy(update=updates) if updates else result


class ConfirmReservationUseCase(_TransitionBase):
    """확정 — 내부 모의 결제 (스펙 2.3절). 결제 호출은 트랜잭션 밖이다."""

    def __init__(self, *, payment: PaymentPort, **deps) -> None:
        super().__init__(**deps)
        self._payment = payment

    def execute(self, *, confirmation_code: str) -> ReservationResult:
        now = self._now()

        # 1) 조회 + 표 판정 (조회 트랜잭션. 판정은 아래 apply_event가 다시 한다)
        with self._tx.read() as session:
            reservation = self._load_by_code(session, confirmation_code)
            current = ReservationStatus(reservation.status)
            resolution = resolve(current, ReservationEvent.CONFIRM)  # 거부면 409
            if resolution.is_idempotent:
                # 이미 CONFIRMED — 결제를 다시 부르지 않는다 (T59)
                return ReservationResult.model_validate(reservation)
            reservation.assert_confirmable(now)  # 만료 대기 중이면 409 (T60)
            reservation_id = reservation.id
            amount = reservation.total_price
            idempotency_key = reservation.idempotency_key

        # 2) 결제 — 트랜잭션 밖 (T61). 여기서 크래시하면 D5의 틈이다
        payment = self._payment.charge(
            reservation_id=reservation_id, amount=amount,
            idempotency_key=idempotency_key,
        )

        # 3) 결과에 따른 전이 (새 트랜잭션)
        event = (
            ReservationEvent.CONFIRM if payment.approved
            else ReservationEvent.PAYMENT_FAILED
        )
        with self._tx.write() as session:
            reservation = self._load_by_code(session, confirmation_code)
            outcome = self._apply_and_settle(session, reservation, event, now)

        if payment.approved and outcome == "lost":
            # 만료·취소가 먼저 이겼다 — 결제를 되돌려 보상한다 (2.3절 실패 표)
            self._payment.refund(transaction_id=payment.transaction_id)
            from app.reservation.domain.errors import InvalidStateTransitionError

            raise InvalidStateTransitionError(
                "확정할 수 없는 상태입니다 (만료 또는 취소됨)"
            )

        with self._tx.read() as session:
            updates = (
                {"failure_reason": payment.decline_reason}
                if not payment.approved else {}
            )
            return self._result(session, confirmation_code, **updates)


class CancelReservationUseCase(_TransitionBase):
    """취소 (스펙 2.4절). **남의 예약은 403이 아니라 404다** — 확인번호의
    존재 자체를 알려주지 않는다."""

    def execute(self, *, confirmation_code: str, user_id: str) -> ReservationResult:
        now = self._now()
        with self._tx.write() as session:
            reservation = self._load_by_code(session, confirmation_code)
            if reservation.user_id != user_id:
                raise ReservationNotFoundError("예약을 찾을 수 없습니다")  # 404 (T67)
            resolution = resolve(
                ReservationStatus(reservation.status), ReservationEvent.CANCEL
            )  # EXPIRED 등이면 409 — "이미 취소됨"이 아니라 "만료됨"이라고 답한다
            if not resolution.is_idempotent:
                self._apply_and_settle(
                    session, reservation, ReservationEvent.CANCEL, now
                )
        with self._tx.read() as session:
            return self._result(session, confirmation_code)


class ExpireReservationsUseCase(_TransitionBase):
    """미결제 만료 (스펙 2.5절). 조회는 후보를 좁힐 뿐, 판정은 건별 트랜잭션의
    apply_event가 한다. 한 건 실패가 나머지를 되돌리지 않는다 (D28)."""

    def __init__(self, *, batch_size: int = 100, **deps) -> None:
        super().__init__(**deps)
        self._batch_size = batch_size

    def execute(self) -> int:
        now = self._now()
        with self._tx.read() as session:  # 조회만
            due_ids = self._reservations.find_due_ids(
                session, now=now, limit=self._batch_size
            )

        expired = 0
        for reservation_id in due_ids:  # 건마다 독립 트랜잭션
            try:
                with self._tx.write() as session:
                    reservation = session.get(Reservation, reservation_id)
                    if reservation is None:
                        continue
                    outcome = self._apply_and_settle(
                        session, reservation, ReservationEvent.EXPIRE, now
                    )
                if outcome == "won":
                    expired += 1
                # lost는 정상이다 — 사용자가 그 사이 확정·취소한 것 (2.5절)
            except Exception:
                # 한 건의 실패가 나머지를 막지 않는다. 삼키지 않고 기록한다
                logger.exception("만료 처리 실패 reservation_id=%s", reservation_id)
        return expired


class CheckInOutUseCase(_TransitionBase):
    """체크인·체크아웃 (스펙 2.6절). 재고는 건드리지 않는다."""

    def check_in(self, *, confirmation_code: str) -> ReservationResult:
        now = self._now()
        today = self._clock.today()
        with self._tx.write() as session:
            reservation = self._load_by_code(session, confirmation_code)
            resolution = resolve(
                ReservationStatus(reservation.status), ReservationEvent.CHECK_IN
            )
            if not resolution.is_idempotent:
                reservation.assert_check_in_window(today)  # T19~T21
                self._apply_and_settle(
                    session, reservation, ReservationEvent.CHECK_IN, now
                )
        with self._tx.read() as session:
            return self._result(session, confirmation_code)

    def check_out(self, *, confirmation_code: str) -> ReservationResult:
        now = self._now()
        with self._tx.write() as session:
            reservation = self._load_by_code(session, confirmation_code)
            resolution = resolve(
                ReservationStatus(reservation.status), ReservationEvent.CHECK_OUT
            )
            if not resolution.is_idempotent:
                self._apply_and_settle(
                    session, reservation, ReservationEvent.CHECK_OUT, now
                )
        with self._tx.read() as session:
            return self._result(session, confirmation_code)


class GetReservationUseCase(_TransitionBase):
    """단건 조회. 소유자 검증은 취소와 같은 이유로 404다."""

    def execute(self, *, confirmation_code: str, user_id: str) -> ReservationResult:
        with self._tx.read() as session:
            reservation = self._load_by_code(session, confirmation_code)
            if reservation.user_id != user_id:
                raise ReservationNotFoundError("예약을 찾을 수 없습니다")
            return ReservationResult.model_validate(reservation)
