"""유스케이스 입출력 — 주문서 형태 Command (스펙 3.6절, D12).

계층을 넘는 그릇이므로 전부 Pydantic이고 `frozen`이다 — 유스케이스가 입력을
고쳐 쓰면 어디서 바뀌었는지 추적할 수 없다.

한때 할인 참조(`discounts`)가 여기 있었다 — 선착순 특가(폐기, ADR-0058)의
입구였는데 구현 없이 자리만 남아 제거했다 (ADR-0065). 단가는 객실타입
정가 하나다.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.reservation.domain.models import GuestCount, StayPeriod


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
