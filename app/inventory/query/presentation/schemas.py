"""검색 응답 스키마 — camelCase 변환은 여기 한 곳뿐이다 (스펙 4절).

`ApiModel` 상속이 변환의 전부다. 상속을 빠뜨리면 그 엔드포인트만 조용히
snake_case로 나가고 서버는 200을 준다 — TDD 20이 키 문자열로 잡는다.
"""

from datetime import date, datetime

from app.common.response import ApiModel
from app.inventory.query.application.commands import EmptyReason, Source


class AvailableRoomTypeResponse(ApiModel):
    room_type_id: int
    room_type_name: str
    capacity: int
    min_remaining: int
    price_per_night: int
    total_price: int


class AvailabilitySearchResponse(ApiModel):
    """요청 에코 + 결과. 낡음 정보(searchedAt·source·staleToleranceSeconds)를
    숨기지 않고 실어 보낸다 (G2). emptyReason·salesOpenUntil은 빈 결과에만
    붙는다 — 라우터가 `response_model_exclude_none`으로 키를 떨군다."""

    hotel_id: int
    check_in: date
    check_out: date
    nights: int
    guest_count: int
    room_count: int
    searched_at: datetime
    source: Source
    stale_tolerance_seconds: int
    items: list[AvailableRoomTypeResponse]
    empty_reason: EmptyReason | None = None
    sales_open_until: date | None = None
