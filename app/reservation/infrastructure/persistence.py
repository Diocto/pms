"""예약 영속성 — 상태 전이 조건부 UPDATE (스펙 3.2절).

**전이 표가 유일한 공급원이다.** 이 파일의 쓰기 경로는 `(현재 상태, 이벤트)`만
받고 다음 상태·재고 복원 여부·이력 값을 전부 `resolve()`에서 얻는다.
표 밖의 (expected, next) 쌍이 UPDATE에 도달할 코드 경로가 없다 (2회차 리뷰).

두 요청이 동시에 같은 예약을 노려도 `WHERE status = :expected` 때문에
하나만 rowcount 1을 받는다. **재고 복원과 이력 기록은 이 1을 받은 쪽만
실행한다** — 이력 INSERT를 이 메서드 안에 묶어 게이트 누락이 불가능하다.
"""

import logging
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from pydantic import BaseModel, ConfigDict
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.models import Reservation, ReservationStatusHistory
from app.reservation.domain.transitions import resolve

logger = logging.getLogger(__name__)


class EventApplication(BaseModel):
    """`apply_event`의 결과.

    - `won` — 전이 성공. 이력이 기록됐고, `restores_inventory`면 호출부가
      **같은 트랜잭션에서** 재고를 복원해야 한다
    - `lost` — 경합 패배. 오류가 아니라 정상 결과다. 아무것도 바뀌지 않았다
    - `idempotent` — 이미 목표 상태. UPDATE도 이력도 없다. 성공으로 응답한다
    """

    model_config = ConfigDict(frozen=True)

    outcome: Literal["won", "lost", "idempotent"]
    restores_inventory: bool


class MySqlReservationRepository:
    def insert(self, session: Session, reservation: Reservation) -> Reservation:
        """INSERT 후 flush로 id를 확정한다. UK 위반은 그대로 올라간다 —
        멱등 UK는 재요청 처리로, 확인번호 UK는 재생성으로 호출부가 가른다."""
        session.add(reservation)
        session.flush()
        return reservation

    def find_by_code(self, session: Session, code: str) -> Reservation | None:
        """전체 일치 조회만 있다. 확인번호 포맷을 파싱하는 코드는 없다 (D7)."""
        return session.execute(
            select(Reservation).where(Reservation.confirmation_code == code)
        ).scalar_one_or_none()

    def find_by_idempotency(
        self, session: Session, *, user_id: str, idempotency_key: str
    ) -> Reservation | None:
        return session.execute(
            select(Reservation).where(
                Reservation.user_id == user_id,
                Reservation.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    def find_due_ids(
        self, session: Session, *, now: datetime, limit: int
    ) -> list[int]:
        """만료 후보를 좁힌다 — **판정이 아니다.** 처리 쪽 apply_event의
        WHERE status='PENDING'이 스스로 다시 판정한다 (D28, 2.5절)."""
        rows = session.execute(
            select(Reservation.id)
            .where(
                Reservation.status == "PENDING",
                Reservation.expires_at <= now,
            )
            .limit(limit)
        ).scalars()
        return list(rows)

    def apply_event(
        self,
        session: Session,
        *,
        reservation_id: int,
        current: ReservationStatus,
        event: ReservationEvent,
        now: datetime,
    ) -> EventApplication:
        """이벤트 하나를 표대로 적용한다 — 판정·UPDATE·이력이 한 몸이다.

        표 밖의 조합이면 `resolve()`가 `InvalidStateTransitionError`를 던진다.
        `confirmed_at`·`terminated_at`도 표의 결과에서 파생한다 — 확정이면
        확정 시각, 종료 상태 도달이면 종료 시각이다.
        """
        resolution = resolve(current, event)  # 표 밖이면 여기서 예외

        if resolution.is_idempotent:
            return EventApplication(outcome="idempotent", restores_inventory=False)

        next_status = resolution.next_status
        assert next_status is not None  # 허용 전이는 항상 다음 상태가 있다

        values: dict = {"status": next_status.value, "updated_at": now}
        if next_status is ReservationStatus.CONFIRMED:
            values["confirmed_at"] = now
        if next_status.is_terminal:
            values["terminated_at"] = now

        result = session.execute(
            update(Reservation)
            .where(
                Reservation.id == reservation_id,
                Reservation.status == current.value,  # ← 이 조건이 승패를 가른다
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            # 경합에서 진 것도 부하테스트 해석의 근거다 (coding-rules.md)
            logger.info(
                "상태 전이 경합 패배 reservation_id=%s current=%s event=%s",
                reservation_id,
                current.value,
                event.value,
            )
            return EventApplication(outcome="lost", restores_inventory=False)

        # 이력은 1을 받은 쪽만, 같은 트랜잭션에서. 값은 전부 표에서 왔다
        session.add(
            ReservationStatusHistory(
                reservation_id=reservation_id,
                from_status=current.value,
                event=event.value,
                to_status=next_status.value,
                occurred_at=now,
            )
        )
        return EventApplication(
            outcome="won", restores_inventory=resolution.restores_inventory
        )
