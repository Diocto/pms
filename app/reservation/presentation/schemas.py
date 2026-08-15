"""요청·응답 스키마 — 전부 `ApiModel` 상속, camelCase로 나간다.

도메인 모델(SQLModel)을 그대로 `response_model`에 달지 않는다 — 내부 `id`와
`idempotency_key`가 새어 나간다. 응답은 `ReservationResult`에서 옮긴다.
"""

from datetime import date, datetime

from app.common.response import ApiModel


class DiscountRefRequest(ApiModel):
    type: str            # "PROMOTION". 유스케이스에서 enum으로 좁힌다
    reference: str


class CreateReservationRequest(ApiModel):
    room_type_id: int
    check_in: date
    check_out: date
    room_count: int
    guest_count: int
    discounts: list[DiscountRefRequest] = []


class ReservationResponse(ApiModel):
    confirmation_code: str
    status: str
    room_type_id: int
    check_in: date
    check_out: date
    room_count: int
    guest_count: int
    price_per_night: int
    total_price: int
    expires_at: datetime
    confirmed_at: datetime | None = None
    terminated_at: datetime | None = None
    created_at: datetime
    failure_reason: str | None = None


class ExpireResponse(ApiModel):
    expired_count: int


class RuntimeConfigResponse(ApiModel):
    """`GET /api/internal/config` (D26).

    **이 응답만 camelCase 규칙의 예외를 품는다** — 바깥 필드(loadTest 등)는
    규칙대로 camelCase지만, `load_test` **안의 키**는 조작자가 셸에 치는
    환경변수 이름 그대로다(dict 내부 키는 alias 변환을 타지 않는다).
    사람이 읽고 셸에 옮겨 적는 유일한 응답이기 때문이다.
    """

    load_test: dict[str, bool | int | float | str]
    implementations: dict[str, str]
    counters: dict[str, int]
    # 응답을 만든 프로세스의 pid. F04가 GET 두 번으로 단일 프로세스를 확인한다 —
    # 워커 수 설정값(선언)이 아니라 실물이다
    process_id: int
