"""reservation 리포지토리 계약. 구현은 `infrastructure/persistence.py`에 있다.

유스케이스는 이 Protocol만 안다 — 구체 클래스를 import하면 DB 없이 테스트할
수 없고 "application은 바깥 두 층을 모른다"가 깨진다 (4회차 리뷰).

구현은 **호출부의 세션을 받아서만 쓴다.** 스스로 세션을 열면 트랜잭션이
갈라진다 (coding-rules.md).
"""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.models import Reservation


class EventApplication(BaseModel):
    """`apply_event`의 결과. 유스케이스 흐름 제어의 값이므로 도메인에 산다.

    - `won` — 전이 성공. 이력이 기록됐고, `restores_inventory`면 호출부가
      **같은 트랜잭션에서** 재고를 복원해야 한다
    - `lost` — 경합 패배. 아무것도 바뀌지 않았다. **스펙 행대로 처리한다** —
      취소·체크인·체크아웃은 409, 만료는 조용히 넘어감, 확정은 보상 후 409
    - `idempotent` — 이미 목표 상태. UPDATE도 이력도 없다
    """

    model_config = ConfigDict(frozen=True)

    outcome: Literal["won", "lost", "idempotent"]
    restores_inventory: bool


class ReservationRepository(Protocol):
    def insert(self, session: Session, reservation: Reservation) -> Reservation: ...

    def find_by_code(self, session: Session, code: str) -> Reservation | None: ...

    def find_by_idempotency(
        self, session: Session, *, user_id: str, idempotency_key: str
    ) -> Reservation | None: ...

    def find_by_user(
        self,
        session: Session,
        *,
        user_id: str,
        status: ReservationStatus | None = None,
    ) -> list[Reservation]:
        """그 사용자의 예약을 **최신순**으로 준다. `status`가 오면 그 상태만.

        목록 API의 공급원이다 — 소유자 필터가 여기 박혀 있어 남의 예약이
        섞일 코드 경로가 없다.
        """
        ...

    def find_due_ids(
        self, session: Session, *, now: datetime, limit: int
    ) -> list[int]: ...

    def apply_event(
        self,
        session: Session,
        *,
        reservation_id: int,
        current: ReservationStatus,
        event: ReservationEvent,
        now: datetime,
    ) -> EventApplication:
        """이벤트 하나를 전이 표대로 적용한다 — 판정·조건부 UPDATE·이력이 한 몸.

        `current`는 **호출부가 행동을 정당화할 때 관찰한 상태**다. 구현이
        상태를 재조회해 판정을 다시 세우면 안 된다 — 판정 기준이 옮겨지면
        경합 패배가 멱등·거부로 위장되어 보상 경로가 사라진다 (4회차 리뷰).
        """
