"""검색 라우터 — 얇다. 쿼리 파라미터를 Query 객체로 옮기고, 유스케이스를
부르고, Result를 응답으로 옮긴다 (clean-architecture.md).

예외를 여기서 잡지 않는다 — StayRange의 400도 진단의 404도 그대로 올라가
전역 핸들러가 HTTP로 바꾼다. 세션도 리포지토리도 여기 없다.
`X-User-Id`를 받지 않는다 — 검색은 익명 호출이다 (D11).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.inventory.application.commands import (
    AvailableRoomsResult,
    SearchAvailableRoomsQuery,
    StayRange,
)
from app.inventory.application.usecases.list_hotels import ListHotelsUseCase
from app.inventory.application.usecases.search_available_rooms import (
    SearchAvailableRoomsUseCase,
)
from app.inventory.presentation import deps
from app.inventory.presentation.schemas import (
    AvailabilitySearchResponse,
    AvailableRoomTypeResponse,
    HotelListResponse,
    HotelResponse,
)

router = APIRouter(prefix="/api", tags=["검색"])


@router.get("/hotels", response_model=HotelListResponse, summary="호텔 목록")
def list_hotels(
    usecase: Annotated[ListHotelsUseCase, Depends(deps.list_hotels_usecase)],
) -> HotelListResponse:
    """호텔 목록과 객실타입 매핑 — 검색 화면용. 검색과 같은 익명 경로다."""
    hotels = usecase.execute()
    return HotelListResponse(
        hotels=[HotelResponse.model_validate(hotel) for hotel in hotels]
    )


@router.get(
    "/availability",
    response_model=AvailabilitySearchResponse,
    response_model_exclude_none=True,  # emptyReason 등은 빈 결과에만 붙는다
    summary="가용 객실 검색",
)
def search_availability(
    usecase: Annotated[
        SearchAvailableRoomsUseCase, Depends(deps.search_available_rooms_usecase)
    ],
    hotel_id: int = Query(alias="hotelId", description="검색할 호텔 id"),
    check_in: date = Query(alias="checkIn", description="체크인 날짜 (YYYY-MM-DD)"),
    check_out: date = Query(
        alias="checkOut", description="체크아웃 날짜 — 체크인보다 뒤여야 한다"
    ),
    guest_count: int = Query(
        alias="guestCount", ge=1, le=20, description="투숙 인원 (1~20)"
    ),
    room_count: int = Query(
        default=1, alias="roomCount", ge=1, le=10, description="객실 수 (1~10)"
    ),
    fresh: bool = Query(
        default=False, description="true면 캐시를 건너뛰고 DB에서 바로 읽는다"
    ),
) -> AvailabilitySearchResponse:
    """기간·인원 조건에 맞는 객실타입과 잔여 수량을 돌려준다.

    기본은 Redis 캐시를 거치며(`source=CACHE`), 잠금 없이 읽는다 — 결과가
    살짝 낡을 수 있고, 최종 확인은 예약 생성이 한다 (ADR-0030). 판매 개시
    전 기간이면 빈 결과에 `emptyReason=NOT_YET_OPEN`과 판매 개시일이 붙는다.
    """
    # 요청 → Query. StayRange 불변식(역전·0박)이 여기서 터지면 400이다
    query = SearchAvailableRoomsQuery(
        hotel_id=hotel_id,
        stay=StayRange(check_in=check_in, check_out=check_out),
        guest_count=guest_count,
        room_count=room_count,
        fresh=fresh,
    )
    result: AvailableRoomsResult = usecase.execute(query)
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
