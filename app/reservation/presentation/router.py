"""예약 라우터 — 얇다. 요청을 Command로 옮기고, 유스케이스를 부르고, Result를
응답으로 옮긴다. 그 셋이 전부다 (clean-architecture.md).

예외를 여기서 잡지 않는다 — 도메인 예외는 그대로 올라가고 전역 핸들러가
HTTP로 바꾼다. 세션도 리포지토리도 여기 없다.

경로 식별자는 내부 id가 아니라 confirmationCode다 (D7).
"""

from fastapi import APIRouter, Header, Query, Request, Response

from app.reservation.application.commands import (
    CreateReservationCommand,
    OrderLine,
    ReservationResult,
)
from app.reservation.domain.enums import ReservationStatus
from app.reservation.domain.models import GuestCount, StayPeriod
from app.reservation.presentation.schemas import (
    CreateReservationRequest,
    ExpireResponse,
    ReservationResponse,
)

router = APIRouter(prefix="/api")


def _to_response(result: ReservationResult) -> ReservationResponse:
    return ReservationResponse.model_validate(result, from_attributes=True)


@router.post("/reservations", response_model=ReservationResponse, status_code=201)
def create_reservation(
    request: Request,
    response: Response,
    body: CreateReservationRequest,
    user_id: str = Header(alias="X-User-Id"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> ReservationResponse:
    # 요청 → Command. VO 불변식(기간·인원·30박)이 여기서 터지면 400이다
    command = CreateReservationCommand(
        user_id=user_id,
        idempotency_key=idempotency_key,
        line=OrderLine(
            room_type_id=body.room_type_id,
            stay_period=StayPeriod(check_in=body.check_in, check_out=body.check_out),
            room_count=body.room_count,
            guest_count=GuestCount(value=body.guest_count),
        ),
        # discounts는 비워 둔다 — 일반 예약 API는 할인을 받지 않는다 (2.2절, D22)
    )
    result = request.app.state.container.reservation.create_reservation().execute(
        command
    )
    if result.replayed:
        response.status_code = 200  # 재요청 — 최초(201)와 상태 코드로 구분한다 (D18)
    return _to_response(result)


@router.get("/reservations", response_model=list[ReservationResponse])
def list_reservations(
    request: Request,
    user_id: str = Header(alias="X-User-Id"),
    status: ReservationStatus | None = Query(default=None),
) -> list[ReservationResponse]:
    """내 예약 목록 — 최신순. `status`가 enum 밖이면 검증 계층이 400을 낸다."""
    results = request.app.state.container.reservation.list_reservations().execute(
        user_id=user_id, status=status
    )
    return [_to_response(result) for result in results]


@router.get("/reservations/{confirmation_code}", response_model=ReservationResponse)
def get_reservation(
    request: Request,
    confirmation_code: str,
    user_id: str = Header(alias="X-User-Id"),
) -> ReservationResponse:
    result = request.app.state.container.reservation.get_reservation().execute(
        confirmation_code=confirmation_code, user_id=user_id
    )
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/confirm", response_model=ReservationResponse
)
def confirm_reservation(
    request: Request,
    confirmation_code: str,
    user_id: str = Header(alias="X-User-Id"),
) -> ReservationResponse:
    result = request.app.state.container.reservation.confirm_reservation().execute(
        confirmation_code=confirmation_code, user_id=user_id
    )
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/cancel", response_model=ReservationResponse
)
def cancel_reservation(
    request: Request,
    confirmation_code: str,
    user_id: str = Header(alias="X-User-Id"),
) -> ReservationResponse:
    result = request.app.state.container.reservation.cancel_reservation().execute(
        confirmation_code=confirmation_code, user_id=user_id
    )
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/check-in", response_model=ReservationResponse
)
def check_in(
    request: Request,
    confirmation_code: str,
    user_id: str = Header(alias="X-User-Id"),
) -> ReservationResponse:
    result = request.app.state.container.reservation.check_in_out().check_in(
        confirmation_code=confirmation_code
    )
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/check-out", response_model=ReservationResponse
)
def check_out(
    request: Request,
    confirmation_code: str,
    user_id: str = Header(alias="X-User-Id"),
) -> ReservationResponse:
    result = request.app.state.container.reservation.check_in_out().check_out(
        confirmation_code=confirmation_code
    )
    return _to_response(result)


@router.post("/internal/reservations/expire", response_model=ExpireResponse)
def expire_reservations(request: Request) -> ExpireResponse:
    """수동 트리거 — 테스트·부하테스트는 주기를 기다릴 수 없다 (2.5절)."""
    expired = request.app.state.container.reservation.expire_reservations().execute()
    return ExpireResponse(expired_count=expired)
