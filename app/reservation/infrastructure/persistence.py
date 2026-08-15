"""예약 영속성 — 상태 전이 조건부 UPDATE (스펙 3.2절).

두 요청이 동시에 같은 예약을 노려도 `WHERE status = :expected` 때문에
하나만 rowcount 1을 받는다. **재고 복원과 이력 기록은 이 1을 받은 쪽만
실행한다** — 그래서 복원은 정확히 한 번이고 이력은 실제 전이와 1:1이다.
"""

import logging
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.models import Reservation, ReservationStatusHistory

logger = logging.getLogger(__name__)


class MySqlReservationRepository:
    def transition(
        self,
        session: Session,
        *,
        reservation_id: int,
        expected: ReservationStatus,
        next_status: ReservationStatus,
        now: datetime,
        confirmed_at: datetime | None = None,
        terminated_at: datetime | None = None,
    ) -> bool:
        """조건부 UPDATE 한 문장. True면 이겼고 False면 경합에서 진 것이다.

        False는 오류가 아니라 정상 결과다 — 확정·취소·만료가 동시에 와도
        하나만 True를 받는 것이 이 설계의 요점이다. 판정은 rowcount로만 한다.
        """
        values: dict = {"status": next_status.value, "updated_at": now}
        if confirmed_at is not None:
            values["confirmed_at"] = confirmed_at
        if terminated_at is not None:
            values["terminated_at"] = terminated_at

        result = session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == expected.value,  # ← 이 조건이 승패를 가른다
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            # 경합에서 진 것도 부하테스트 해석의 근거다 (coding-rules.md)
            logger.info(
                "상태 전이 경합 패배 reservation_id=%s expected=%s next=%s",
                reservation_id,
                expected.value,
                next_status.value,
            )
        return result.rowcount == 1

    def append_history(
        self,
        session: Session,
        *,
        reservation_id: int,
        from_status: ReservationStatus,
        event: ReservationEvent,
        to_status: ReservationStatus,
        occurred_at: datetime,
    ) -> None:
        """전이 UPDATE가 1건일 때만 부른다. 그래서 이력은 실제 전이와 1:1이다."""
        session.add(
            ReservationStatusHistory(
                reservation_id=reservation_id,
                from_status=from_status.value,
                event=event.value,
                to_status=to_status.value,
                occurred_at=occurred_at,
            )
        )
