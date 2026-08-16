"""검색 라우터 — 얇다. 쿼리 파라미터를 Query 객체로 옮기고, 유스케이스를
부르고, Result를 응답으로 옮긴다 (clean-architecture.md).

예외를 여기서 잡지 않는다 — StayRange의 400도 진단의 404도 그대로 올라가
전역 핸들러가 HTTP로 바꾼다. 세션도 리포지토리도 여기 없다.
`X-User-Id`를 받지 않는다 — 검색은 익명 호출이다 (D17).
"""

from datetime import date

from fastapi import APIRouter, Query, Request

from app.inventory.query.application.commands import (
    AvailableRoomsResult,
    SearchAvailableRoomsQuery,
    StayRange,
)
from app.inventory.query.presentation.schemas import (
    AvailabilitySearchResponse,
    AvailableRoomTypeResponse,
    HotelListResponse,
    HotelResponse,
)

router = APIRouter(prefix="/api")


@router.get("/hotels", response_model=HotelListResponse)
def list_hotels(request: Request) -> HotelListResponse:
    """호텔 목록과 객실타입 매핑 — F05 검색 화면용. 검색과 같은 익명 경로다."""
    hotels = request.app.state.container.inventory_query.list_hotels().execute()
    return HotelListResponse(
        hotels=[HotelResponse.model_validate(hotel) for hotel in hotels]
    )


@router.get(
    "/availability",
    response_model=AvailabilitySearchResponse,
    response_model_exclude_none=True,  # emptyReason 등은 빈 결과에만 붙는다
)
def search_availability(
    request: Request,
    hotel_id: int = Query(alias="hotelId"),
    check_in: date = Query(alias="checkIn"),
    check_out: date = Query(alias="checkOut"),
    guest_count: int = Query(alias="guestCount", ge=1),
    room_count: int = Query(alias="roomCount", ge=1),
    fresh: bool = Query(default=False),
) -> AvailabilitySearchResponse:
    # 요청 → Query. StayRange 불변식(역전·0박·31박)이 여기서 터지면 400이다
    query = SearchAvailableRoomsQuery(
        hotel_id=hotel_id,
        stay=StayRange(check_in=check_in, check_out=check_out),
        guest_count=guest_count,
        room_count=room_count,
        fresh=fresh,
    )
    result: AvailableRoomsResult = (
        request.app.state.container.inventory_query.search_available_rooms().execute(
            query
        )
    )
    return AvailabilitySearchResponse(
        hotel_id=query.hotel_id,
        check_in=query.stay.check_in,
        check_out=query.stay.check_out,
        nights=query.stay.nights(),
        guest_count=query.guest_count,
        room_count=query.room_count,
        searched_at=result.searched_at,
        source=result.source,
        stale_tolerance_seconds=result.stale_tolerance_seconds,
        items=[
            AvailableRoomTypeResponse.model_validate(item) for item in result.items
        ],
        empty_reason=result.empty_reason,
        sales_open_until=result.sales_open_until,
    )
