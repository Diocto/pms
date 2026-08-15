"""전이 표 — 상태머신의 유일한 진실 (스펙 1.4절, ADR-0003).

`(현재 상태, 이벤트) → 다음 상태`를 **이 표로만** 판단한다. if-else 분기로
전이하지 않고, 외부는 이벤트만 던진다. `resolve()`가 유일한 조회 경로이므로
**표 밖의 (expected, next) 쌍이 만들어질 코드 경로 자체가 없다** (1회차 리뷰 지침).

재고 복원 여부도 표의 값이다. "복원은 상태 전이의 결과"(3.2절)라는 설계에서
어느 전이가 복원을 일으키는지는 상태머신의 사실이지 유스케이스의 판단이 아니다.

허용 7 + 멱등 6 + 거부 23 = 36. 스펙 1.4절 표와 1:1이고 T15가 그것을 고정한다.
"""

from pydantic import BaseModel, ConfigDict

from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.errors import InvalidStateTransitionError

_S = ReservationStatus
_E = ReservationEvent


class Resolution(BaseModel):
    """전이 판정 결과.

    - 허용: `next_status`로 간다. `restores_inventory`면 복원이 뒤따른다
    - 멱등: 상태를 바꾸지 않고 성공으로 응답한다. **재고는 절대 건드리지 않는다**
    """

    model_config = ConfigDict(frozen=True)

    is_idempotent: bool
    next_status: ReservationStatus | None
    restores_inventory: bool


# (현재, 이벤트) → (다음, 재고 복원). 스펙 1.4절 「허용 전이 상세」 7줄과 1:1
ALLOWED: dict[
    tuple[ReservationStatus, ReservationEvent], Resolution
] = {
    (_S.PENDING, _E.CONFIRM): Resolution(
        is_idempotent=False, next_status=_S.CONFIRMED, restores_inventory=False
    ),
    (_S.PENDING, _E.PAYMENT_FAILED): Resolution(
        is_idempotent=False, next_status=_S.CANCELLED, restores_inventory=True
    ),
    (_S.PENDING, _E.CANCEL): Resolution(
        is_idempotent=False, next_status=_S.CANCELLED, restores_inventory=True
    ),
    (_S.PENDING, _E.EXPIRE): Resolution(
        is_idempotent=False, next_status=_S.EXPIRED, restores_inventory=True
    ),
    (_S.CONFIRMED, _E.CANCEL): Resolution(
        is_idempotent=False, next_status=_S.CANCELLED, restores_inventory=True
    ),
    (_S.CONFIRMED, _E.CHECK_IN): Resolution(
        is_idempotent=False, next_status=_S.CHECKED_IN, restores_inventory=False
    ),
    (_S.CHECKED_IN, _E.CHECK_OUT): Resolution(
        is_idempotent=False, next_status=_S.CHECKED_OUT, restores_inventory=False
    ),
}

# 이미 목표 상태다 — 바꾸지 않고 성공으로 답한다. 스펙 1.4절 멱등 6칸과 1:1
IDEMPOTENT: frozenset[tuple[ReservationStatus, ReservationEvent]] = frozenset(
    {
        (_S.CONFIRMED, _E.CONFIRM),
        (_S.CHECKED_IN, _E.CHECK_IN),
        (_S.CHECKED_OUT, _E.CHECK_OUT),
        (_S.CANCELLED, _E.PAYMENT_FAILED),
        (_S.CANCELLED, _E.CANCEL),
        (_S.EXPIRED, _E.EXPIRE),
    }
)

_IDEMPOTENT_RESOLUTION = Resolution(
    is_idempotent=True, next_status=None, restores_inventory=False
)


def resolve(
    current: ReservationStatus, event: ReservationEvent
) -> Resolution:
    """표를 조회한다. 표 밖이면 `InvalidStateTransitionError`.

    메시지에 현재 상태를 싣는다 — `EXPIRED + CANCEL` 거부를 받은 사용자는
    "이미 취소됨"이 아니라 "만료됨"이라고 들어야 한다 (1.4절 읽는 법).
    """
    if (current, event) in ALLOWED:
        return ALLOWED[(current, event)]
    if (current, event) in IDEMPOTENT:
        return _IDEMPOTENT_RESOLUTION
    raise InvalidStateTransitionError(
        f"{current.value} 상태에서는 {event.value} 이벤트를 처리할 수 없습니다"
    )
