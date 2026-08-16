"""상태 전이 유스케이스들 — 확정·취소·체크인·체크아웃·만료 (스펙 2.3~2.6절).

넷의 뼈대가 같다: 조회 → 표 판정(resolve) → [시간창 검증] → apply_event.

**판정을 정당화한 상태(expected)를 조건부 UPDATE에 그대로 건다** — 재조회한
상태로 판정을 다시 세우면 경합 패배가 멱등·거부로 위장되어 보상 경로가
사라진다 (4회차 리뷰의 수렴 지적). `lost`의 처리는 유스케이스마다 스펙 행을
따른다: 취소·체크인·체크아웃은 409, 확정은 **보상(환불) 후 409**, 만료는
정상 흐름으로 조용히 넘어간다.

**복원과 반납 훅은 전이에서 이긴 쪽만** — apply_event가 rowcount 1을 받은
트랜잭션 안에서만 부른다. 이것이 이중 복원(C6)을 막는 유일한 논리다 (3.2절).
"""

import logging
from datetime import datetime

from app.common.clock import Clock
from app.common.db import TransactionManager
from app.inventory.domain.repositories import InventoryRepository
from app.reservation.application.commands import ReservationResult
from app.reservation.application.ports import PaymentPort, ReservationReleaseHook
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.errors import (
    InvalidStateTransitionError,
    ReservationNotFoundError,
)
from app.reservation.domain.models import Reservation, StayPeriod
from app.reservation.domain.repositories import ReservationRepository
from app.reservation.domain.transitions import resolve

logger = logging.getLogger(__name__)


class _TransitionBase:
    def __init__(
        self,
        *,
        tx: TransactionManager,
        inventory_repository: InventoryRepository,
        reservation_repository: ReservationRepository,
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
        self,
        session,
        reservation: Reservation,
        *,
        expected: ReservationStatus,
        event: ReservationEvent,
        now: datetime,
    ) -> str:
        """전이를 적용하고, 이긴 쪽만 복원·반납 훅을 태운다. outcome을 돌려준다.

        `expected`는 호출부가 행동을 정당화할 때 관찰한 상태다 — 재조회하지
        않는다. 표 밖 조합은 apply_event 안의 resolve()가 던진다.
        """
        applied = self._reservations.apply_event(
            session,
            reservation_id=reservation.id,
            current=expected,
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
                hook.on_released(session, reservation.id, expected, event)
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

    def execute(self, *, confirmation_code: str, user_id: str) -> ReservationResult:
        now = self._now()

        # 1) 조회 + 표 판정 — 이 시점의 PENDING이 결제를 정당화한다
        with self._tx.read() as session:
            reservation = self._load_by_code(session, confirmation_code)
            if reservation.user_id != user_id:
                # 남의 예약은 404다 (관리자 지시 2026-08-16, D33) — 확인번호만
                # 알면 제3자가 남의 결제를 일으킬 수 있던 문을 닫는다
                raise ReservationNotFoundError("예약을 찾을 수 없습니다")
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

        # 3) 전이 — 결제를 정당화한 PENDING을 그대로 건다. 그 사이 누가
        #    끼어들었든(취소·만료·다른 확정) WHERE가 0건을 받아 lost가 되고,
        #    승인 건이면 아래 보상 분기 **하나로** 전부 수렴한다
        event = (
            ReservationEvent.CONFIRM if payment.approved
            else ReservationEvent.PAYMENT_FAILED
        )
        with self._tx.write() as session:
            reservation = self._load_by_code(session, confirmation_code)  # 복원 파라미터용
            outcome = self._apply_and_settle(
                session,
                reservation,
                expected=ReservationStatus.PENDING,
                event=event,
                now=now,
            )

        if outcome == "lost":
            if payment.approved:
                # 만료·취소·다른 확정이 먼저 이겼다 — 내 결제를 되돌린다 (2.3절).
                # 이중 확정 창에서도 패배자가 자기 charge를 보상하므로
                # 예약 하나에 결제가 두 건 남지 않는다
                self._payment.refund(transaction_id=payment.transaction_id)
                raise InvalidStateTransitionError(
                    "확정할 수 없는 상태입니다 (만료·취소되었거나 이미 확정됨)"
                )
            # 거절 + 패배: 승자가 이미 상태·재고를 정리했다. 현재 상태를 돌려준다
            with self._tx.read() as session:
                return self._result(
                    session, confirmation_code,
                    failure_reason=payment.decline_reason,
                )

        updates = {} if payment.approved else {"failure_reason": payment.decline_reason}
        with self._tx.read() as session:
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
            current = ReservationStatus(reservation.status)
            resolution = resolve(current, ReservationEvent.CANCEL)
            # EXPIRED 등이면 위에서 409 — "이미 취소됨"이 아니라 "만료됨"이라 답한다
            if not resolution.is_idempotent:
                outcome = self._apply_and_settle(
                    session, reservation,
                    expected=current, event=ReservationEvent.CANCEL, now=now,
                )
                if outcome == "lost":
                    # 확정·만료가 그 사이 이겼다 — 둘 중 하나만 200이다 (2.4절)
                    raise InvalidStateTransitionError(
                        "취소할 수 없는 상태입니다 (경합에서 다른 전이가 먼저 처리됨)"
                    )
        with self._tx.read() as session:
            return self._result(session, confirmation_code)


class ExpireReservationsUseCase(_TransitionBase):
    """미결제 만료 (스펙 2.5절). 조회는 후보를 좁힐 뿐이고 판정은 건별
    트랜잭션의 `WHERE status='PENDING'`이 한다 (D28).

    **경합 패배가 정상 흐름인 유일한 유스케이스다** — 사용자가 그 사이
    확정·취소했으면 아무것도 하지 않고 넘어간다."""

    def __init__(self, *, batch_size: int, **deps) -> None:
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
                    # expected는 후보의 근거였던 PENDING이다 — 재조회한 상태로
                    # 판정하지 않는다. 그 사이 확정됐으면 예외가 아니라
                    # 0건(lost)으로 조용히 끝난다 (2.5절 "정상 흐름")
                    outcome = self._apply_and_settle(
                        session, reservation,
                        expected=ReservationStatus.PENDING,
                        event=ReservationEvent.EXPIRE,
                        now=now,
                    )
                if outcome == "won":
                    expired += 1
            except Exception:
                # 진짜 실패(복원 불일치 등)만 여기 온다. 한 건의 실패가
                # 나머지를 막지 않는다. 삼키지 않고 기록한다 (T71)
                logger.exception("만료 처리 실패 reservation_id=%s", reservation_id)
        return expired


class CheckInOutUseCase(_TransitionBase):
    """체크인·체크아웃 (스펙 2.6절). 재고는 건드리지 않는다."""

    def _transition(
        self, *, confirmation_code: str, event: ReservationEvent, check_window: bool
    ) -> ReservationResult:
        now = self._now()
        today = self._clock.today()
        with self._tx.write() as session:
            reservation = self._load_by_code(session, confirmation_code)
            current = ReservationStatus(reservation.status)
            resolution = resolve(current, event)
            if not resolution.is_idempotent:
                if check_window:
                    reservation.assert_check_in_window(today)  # T19~T21
                outcome = self._apply_and_settle(
                    session, reservation, expected=current, event=event, now=now
                )
                if outcome == "lost":
                    raise InvalidStateTransitionError(
                        "처리할 수 없는 상태입니다 (경합에서 다른 전이가 먼저 처리됨)"
                    )
        with self._tx.read() as session:
            return self._result(session, confirmation_code)

    def check_in(self, *, confirmation_code: str) -> ReservationResult:
        return self._transition(
            confirmation_code=confirmation_code,
            event=ReservationEvent.CHECK_IN,
            check_window=True,
        )

    def check_out(self, *, confirmation_code: str) -> ReservationResult:
        return self._transition(
            confirmation_code=confirmation_code,
            event=ReservationEvent.CHECK_OUT,
            check_window=False,
        )


class GetReservationUseCase(_TransitionBase):
    """단건 조회. 소유자 검증은 취소와 같은 이유로 404다."""

    def execute(self, *, confirmation_code: str, user_id: str) -> ReservationResult:
        with self._tx.read() as session:
            reservation = self._load_by_code(session, confirmation_code)
            if reservation.user_id != user_id:
                raise ReservationNotFoundError("예약을 찾을 수 없습니다")
            return ReservationResult.model_validate(reservation)


class ListReservationsUseCase(_TransitionBase):
    """목록 조회 — 자기 예약만 최신순 (F05 요청, 관리자 지시 2026-08-16).

    단건 조회의 404 존재 은닉과 충돌하지 않는다 — 소유자 필터가 조회
    조건에 박혀 있어 남의 예약은 애초에 결과에 없고, 없는 사용자는
    빈 배열이라 존재 여부를 새로 알려주는 것이 없다.
    """

    def execute(
        self, *, user_id: str, status: ReservationStatus | None = None
    ) -> list[ReservationResult]:
        with self._tx.read() as session:
            reservations = self._reservations.find_by_user(
                session, user_id=user_id, status=status
            )
            return [
                ReservationResult.model_validate(reservation)
                for reservation in reservations
            ]
