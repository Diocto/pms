"""사용권 전이 표 — 상태머신의 유일한 진실 (스펙 4절).

`(현재 상태, 이벤트) → 판정`을 이 표로만 한다. if-else 분기로 전이하지 않고,
외부는 이벤트만 던진다. F01의 `reservation/domain/transitions.py`와 같은 구조다
— 두 상태머신을 같은 눈으로 읽을 수 있게 형태를 맞췄다.

허용 1 + 멱등 1 = 2가 지금의 전 조합이다(상태 2 × 이벤트 1). 거부 조합이
0개인 것은 우연이고, 이벤트가 추가되는 순간 표 밖 조합이 자동으로 거부되는
것을 T9 전수 루프가 고정한다.
"""

from pydantic import BaseModel, ConfigDict

from app.common.errors import InvalidRequestError
from app.promotion.domain.enums import ClaimEvent, ClaimStatus


class Resolution(BaseModel):
    """전이 판정 결과.

    - 허용: `next_status`로 간다. `restores_inventory`면 특가 재고 복원이 뒤따른다
    - 멱등: 상태를 바꾸지 않고 성공으로 응답한다. **재고는 절대 되돌리지 않는다**
      — 이중 반납은 조건부 UPDATE 0건으로 판정된다 (스펙 §6, T28)
    """

    model_config = ConfigDict(frozen=True)

    is_idempotent: bool
    next_status: ClaimStatus | None
    restores_inventory: bool


ALLOWED: dict[tuple[ClaimStatus, ClaimEvent], Resolution] = {
    (ClaimStatus.USED, ClaimEvent.RELEASE): Resolution(
        is_idempotent=False,
        next_status=ClaimStatus.RELEASED,
        restores_inventory=True,
    ),
}

IDEMPOTENT: frozenset[tuple[ClaimStatus, ClaimEvent]] = frozenset(
    {
        (ClaimStatus.RELEASED, ClaimEvent.RELEASE),
    }
)

_IDEMPOTENT_RESOLUTION = Resolution(
    is_idempotent=True, next_status=None, restores_inventory=False
)


def resolve(current: ClaimStatus, event: ClaimEvent) -> Resolution:
    """표를 조회한다. 표 밖이면 `InvalidRequestError`."""
    if (current, event) in ALLOWED:
        return ALLOWED[(current, event)]
    if (current, event) in IDEMPOTENT:
        return _IDEMPOTENT_RESOLUTION
    raise InvalidRequestError(
        f"{current.value} 상태의 사용권은 {event.value} 이벤트를 처리할 수 없습니다"
    )
