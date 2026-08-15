"""재고 차감·복원 조건부 UPDATE — 이 시스템 동시성 제어의 심장 (스펙 3.2절).

읽고-판단하고-쓰는 세 단계를 UPDATE 한 문장으로 줄인다. `rowcount`가 승패다:
1이면 이겼고 0이면 부족했던 것이다. 락도 재시도도 필요 없다.
"""

import logging
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.inventory.domain.errors import (
    InsufficientInventoryError,
    InventoryRestoreMismatchError,
)
from app.inventory.domain.models import RoomDailyInventory

logger = logging.getLogger(__name__)


class MySqlInventoryRepository:
    def deduct(
        self,
        session: Session,
        *,
        room_type_id: int,
        stay_dates: Sequence[date],
        room_count: int,
        now: datetime,
    ) -> None:
        # 정렬은 여기서만 한다. 분산락과 같은 오름차순이어야 락을 껐을 때도
        # InnoDB 행 락이 같은 순서로 잡혀 데드락이 나지 않는다 (D10, 3.3절)
        for stay_date in sorted(set(stay_dates)):
            result = session.execute(
                update(RoomDailyInventory)
                .where(
                    RoomDailyInventory.room_type_id == room_type_id,
                    RoomDailyInventory.stay_date == stay_date,
                    RoomDailyInventory.remaining >= room_count,  # ← 이 조건이 방어선이다
                )
                .values(
                    remaining=RoomDailyInventory.remaining - room_count,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 0:
                # 부하테스트 결과 해석의 근거가 되는 로그 (coding-rules.md)
                logger.info(
                    "재고 부족 room_type_id=%s stay_date=%s count=%s",
                    room_type_id,
                    stay_date,
                    room_count,
                )
                raise InsufficientInventoryError(
                    f"{stay_date}의 잔여 객실이 부족합니다"
                )

    def restore(
        self,
        session: Session,
        *,
        room_type_id: int,
        stay_dates: Sequence[date],
        room_count: int,
        now: datetime,
    ) -> None:
        ordered = sorted(set(stay_dates))
        restored = 0
        for stay_date in ordered:
            result = session.execute(
                update(RoomDailyInventory)
                .where(
                    RoomDailyInventory.room_type_id == room_type_id,
                    RoomDailyInventory.stay_date == stay_date,
                    # 상한 조건은 이중 복원의 감지 장치다. 3.2절의 "복원은 상태
                    # 전이의 결과" 논리가 깨졌을 때 여기서 0건이 나온다
                    RoomDailyInventory.remaining + room_count
                    <= RoomDailyInventory.total_quantity,
                )
                .values(
                    remaining=RoomDailyInventory.remaining + room_count,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            restored += result.rowcount
        if restored != len(ordered):
            logger.error(
                "복원 갱신 행 수 불일치 room_type_id=%s expected=%s actual=%s",
                room_type_id,
                len(ordered),
                restored,
            )
            raise InventoryRestoreMismatchError(
                f"복원 대상 {len(ordered)}행 중 {restored}행만 갱신됐다. "
                "이중 복원이 의심된다"
            )
