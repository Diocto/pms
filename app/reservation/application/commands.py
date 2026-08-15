"""유스케이스 입출력 — 주문서 형태 Command (스펙 3.6절, D12).

계층을 넘는 그릇이므로 전부 Pydantic이고 `frozen`이다 — 유스케이스가 입력을
고쳐 쓰면 어디서 바뀌었는지 추적할 수 없다.

`discounts`가 비어 있으면 정가 예약이다. **할인은 명시적으로 요청해야만
적용된다** — 자동 적용하면 일반가로 예약하려는 사용자까지 특가를 소진시킨다.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.reservation.domain.models import GuestCount, StayPeriod


class DiscountType(str, Enum):
    PROMOTION = "PROMOTION"      # COUPON이 생기면 여기 추가된다


class DiscountRef(BaseModel):
    """어떤 할인을 적용할지 가리키는 참조. F01은 할인의 내용을 모른다."""

    model_config = ConfigDict(frozen=True)

    type: DiscountType
    reference: str


class OrderLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    room_type_id: int
    stay_period: StayPeriod
    room_count: int
    guest_count: GuestCount


class CreateReservationCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    idempotency_key: str
    line: OrderLine
    discounts: list[DiscountRef] = []          # 지금은 0개 또는 1개


class ReservationResult(BaseModel):
    """유스케이스 출력. 도메인 모델을 그대로 응답에 내보내지 않기 위한 그릇이다 —
    내부 `id`·`idempotency_key`는 여기 없다."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    confirmation_code: str
    status: str
    room_type_id: int
    check_in: "date"
    check_out: "date"
    room_count: int
    guest_count: int
    price_per_night: int
    total_price: int
    expires_at: "datetime"
    confirmed_at: "datetime | None" = None
    terminated_at: "datetime | None" = None
    created_at: "datetime"
    failure_reason: str | None = None    # 결제 거절 시 PAYMENT_DECLINED (2.3절)
    replayed: bool = False               # 멱등 재요청이면 True — 라우터가 200/201을 가른다
