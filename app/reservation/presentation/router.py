"""예약 라우터 — 얇다. 요청을 Command로 옮기고, 유스케이스를 부르고, Result를
응답으로 옮긴다. 그 셋이 전부다 (clean-architecture.md).

**의존은 서명에 선언한다 (ADR-0064).** 유스케이스는 `deps`의 제공자로 받는다.
엔드포인트 본문에 컨테이너가 나타나지 않는다.

예외를 여기서 잡지 않는다 — 도메인 예외는 그대로 올라가고 전역 핸들러가
HTTP로 바꾼다. 세션도 리포지토리도 여기 없다.

Swagger 문서는 화면(프론트엔드) 개발자가 읽는 것을 기준으로 쓴다.
에러 응답의 코드·상태 계약은 `app/common/error_codes.py`가 정본이다.

경로 식별자는 내부 id가 아니라 confirmationCode다 (D7).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response

from app.reservation.application.commands import (
    CreateReservationCommand,
    OrderLine,
    ReservationResult,
)
from app.reservation.application.usecases.create_reservation import (
    CreateReservationUseCase,
)
from app.reservation.application.usecases.transition_reservation import (
    CancelReservationUseCase,
    CheckInOutUseCase,
    ConfirmReservationUseCase,
    ExpireReservationsUseCase,
    GetReservationUseCase,
    ListReservationsUseCase,
)
from app.reservation.domain.enums import ReservationStatus
from app.reservation.domain.models import GuestCount, StayPeriod
from app.reservation.presentation import deps
from app.reservation.presentation.schemas import (
    CreateReservationRequest,
    ExpireResponse,
    ReservationResponse,
)

router = APIRouter(prefix="/api", tags=["예약"])

# 모든 예약 API가 요구하는 헤더 — Swagger 표기를 한 곳에서 정의한다
_USER_ID_HEADER = Header(
    alias="X-User-Id",
    description="요청 사용자 식별자. 로그인 대용이며 인증이 아니다 (ADR-0006)",
)

# 확정 코드로 단건을 다루는 API가 공유하는 404 문구
_NOT_FOUND_404 = {
    "description": "예약이 없거나 내 예약이 아님 (RESOURCE_NOT_FOUND)"
}


def _to_response(result: ReservationResult) -> ReservationResponse:
    return ReservationResponse.model_validate(result, from_attributes=True)


@router.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=201,
    summary="예약 생성",
    responses={
        200: {
            "description": "같은 Idempotency-Key의 재요청 — 이전에 만든 예약을 그대로 돌려줌",
            "model": ReservationResponse,
        },
        400: {"description": "입력이 잘못됨 — 날짜 역전, 인원·객실 수 범위 밖, 필수 헤더 누락 (INVALID_REQUEST)"},
        404: {"description": "객실타입이 없음 (RESOURCE_NOT_FOUND)"},
        409: {"description": "남은 객실이 부족함 (INSUFFICIENT_INVENTORY) · 같은 키의 요청이 아직 처리 중 (REQUEST_IN_PROGRESS)"},
        503: {"description": "혼잡으로 잠시 처리 못 함 — 같은 요청을 그대로 다시 보내면 됨 (LOCK_ACQUISITION_FAILED)"},
    },
)
def create_reservation(
    response: Response,
    body: CreateReservationRequest,
    usecase: Annotated[
        CreateReservationUseCase, Depends(deps.create_reservation_usecase)
    ],
    user_id: str = _USER_ID_HEADER,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        description="중복 생성을 막는 키. 요청마다 새로 만들되, 재시도할 때는 같은 키를 다시 보낸다",
    ),
) -> ReservationResponse:
    """객실을 예약합니다.

    만들어진 예약은 결제 대기(`PENDING`) 상태이고 재고는 이 시점에 확보됩니다.
    제한 시간 안에 결제(확정)하지 않으면 자동으로 만료됩니다.

    네트워크 오류 등으로 재시도할 때 같은 `Idempotency-Key`를 보내면 예약이
    중복 생성되지 않고 이전 결과를 그대로 받습니다 — 새로 만들어지면 201,
    재요청이면 200입니다.
    """
    # 요청 → Command. VO 불변식(기간·인원)이 여기서 터지면 400이다
    command = CreateReservationCommand(
        user_id=user_id,
        idempotency_key=idempotency_key,
        line=OrderLine(
            room_type_id=body.room_type_id,
            stay_period=StayPeriod(check_in=body.check_in, check_out=body.check_out),
            room_count=body.room_count,
            guest_count=GuestCount(value=body.guest_count),
        ),
    )
    result = usecase.execute(command)
    if result.replayed:
        response.status_code = 200  # 재요청 — 최초(201)와 상태 코드로 구분한다 (D18)
    return _to_response(result)


@router.get(
    "/reservations",
    response_model=list[ReservationResponse],
    summary="내 예약 목록",
    responses={
        400: {"description": "status 값이 잘못됐거나 헤더 누락 (INVALID_REQUEST)"},
    },
)
def list_reservations(
    usecase: Annotated[ListReservationsUseCase, Depends(deps.list_reservations_usecase)],
    user_id: str = _USER_ID_HEADER,
    status: ReservationStatus | None = Query(
        default=None, description="이 상태의 예약만 돌려받는다. 비우면 전체"
    ),
) -> list[ReservationResponse]:
    """내 예약 목록을 최신순으로 돌려줍니다. `status`로 특정 상태만 걸러볼 수 있습니다."""
    results = usecase.execute(user_id=user_id, status=status)
    return [_to_response(result) for result in results]


@router.get(
    "/reservations/{confirmation_code}",
    response_model=ReservationResponse,
    summary="예약 상세 조회",
    responses={404: _NOT_FOUND_404},
)
def get_reservation(
    confirmation_code: str,
    usecase: Annotated[GetReservationUseCase, Depends(deps.get_reservation_usecase)],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """예약 확정 코드로 예약 상세를 조회합니다."""
    result = usecase.execute(confirmation_code=confirmation_code, user_id=user_id)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/confirm",
    response_model=ReservationResponse,
    summary="결제 완료 처리 (예약 확정)",
    responses={
        404: _NOT_FOUND_404,
        409: {"description": "결제할 수 없는 상태 — 이미 취소·만료된 예약 (INVALID_STATE_TRANSITION)"},
    },
)
def confirm_reservation(
    confirmation_code: str,
    usecase: Annotated[
        ConfirmReservationUseCase, Depends(deps.confirm_reservation_usecase)
    ],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """결제 완료 처리를 진행합니다. 결제(모의)가 승인되면 예약이 `CONFIRMED`가 됩니다.

    결제가 거절되면 HTTP 오류가 아니라 정상 응답으로 돌아오며, `status`가
    `CANCELLED`이고 `failureReason`에 `PAYMENT_DECLINED`가 담깁니다 —
    화면은 이 필드로 결제 실패 안내를 띄우면 됩니다.
    """
    result = usecase.execute(confirmation_code=confirmation_code, user_id=user_id)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/cancel",
    response_model=ReservationResponse,
    summary="예약 취소",
    responses={
        404: _NOT_FOUND_404,
        409: {"description": "취소할 수 없는 상태 — 이미 체크인한 예약 (INVALID_STATE_TRANSITION)"},
    },
)
def cancel_reservation(
    confirmation_code: str,
    usecase: Annotated[
        CancelReservationUseCase, Depends(deps.cancel_reservation_usecase)
    ],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """예약을 취소합니다. 차감됐던 재고는 되돌아갑니다.

    이미 취소된 예약에 다시 호출해도 오류가 아니라 성공 응답을 받습니다 —
    취소 버튼의 중복 클릭을 화면에서 따로 막지 않아도 됩니다.
    """
    result = usecase.execute(confirmation_code=confirmation_code, user_id=user_id)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/check-in",
    response_model=ReservationResponse,
    summary="체크인",
    responses={
        404: _NOT_FOUND_404,
        409: {"description": "체크인할 수 없는 상태 — 결제 완료 전이거나 이미 투숙 중 (INVALID_STATE_TRANSITION)"},
    },
)
def check_in(
    confirmation_code: str,
    usecase: Annotated[CheckInOutUseCase, Depends(deps.check_in_out_usecase)],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """체크인 처리를 합니다. 결제가 끝난(`CONFIRMED`) 예약만 체크인할 수 있습니다."""
    result = usecase.check_in(confirmation_code=confirmation_code)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/check-out",
    response_model=ReservationResponse,
    summary="체크아웃",
    responses={
        404: _NOT_FOUND_404,
        409: {"description": "체크아웃할 수 없는 상태 — 체크인 전 (INVALID_STATE_TRANSITION)"},
    },
)
def check_out(
    confirmation_code: str,
    usecase: Annotated[CheckInOutUseCase, Depends(deps.check_in_out_usecase)],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """체크아웃 처리를 합니다. 투숙 중(`CHECKED_IN`)인 예약만 체크아웃할 수 있습니다."""
    result = usecase.check_out(confirmation_code=confirmation_code)
    return _to_response(result)


@router.post(
    "/internal/reservations/expire",
    response_model=ExpireResponse,
    summary="미결제 만료 일괄 처리 (운영용)",
)
def expire_reservations(
    usecase: Annotated[
        ExpireReservationsUseCase, Depends(deps.expire_reservations_usecase)
    ],
) -> ExpireResponse:
    """결제 대기 시간이 지난 예약을 일괄 만료 처리합니다.

    평소에는 서버가 30초마다 자동으로 실행하므로 화면에서 부를 일은 없습니다.
    테스트·부하테스트가 만료 시점을 제어할 때 씁니다.
    """
    expired = usecase.execute()
    return ExpireResponse(expired_count=expired)
