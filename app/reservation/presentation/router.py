"""예약 라우터 — 얇다. 요청을 Command로 옮기고, 유스케이스를 부르고, Result를
응답으로 옮긴다. 그 셋이 전부다 (clean-architecture.md).

**의존은 서명에 선언한다 (ADR-0064).** 유스케이스는 `deps`의 제공자로 받는다.
엔드포인트 본문에 컨테이너가 나타나지 않는다.

예외를 여기서 잡지 않는다 — 도메인 예외는 그대로 올라가고 전역 핸들러가
HTTP로 바꾼다. 세션도 리포지토리도 여기 없다.

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
    description="요청 사용자 식별자. 인증이 아니라 식별이다 (ADR-0006)",
)


def _to_response(result: ReservationResult) -> ReservationResponse:
    return ReservationResponse.model_validate(result, from_attributes=True)


@router.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=201,
    summary="예약 생성 (멱등)",
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
        description="중복 생성을 막는 키. 같은 키의 재시도는 저장된 결과를 돌려받는다",
    ),
) -> ReservationResponse:
    """PENDING 예약을 만들고 날짜별 재고를 차감한다.

    같은 `Idempotency-Key`의 재요청은 새 예약을 만들지 않고 저장된 결과를
    돌려준다 — 최초 생성은 201, 재요청은 200이다 (D18). 어느 날짜든 재고가
    부족하면 409이고, 그때는 아무 날짜도 차감되지 않는다.
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
)
def list_reservations(
    usecase: Annotated[ListReservationsUseCase, Depends(deps.list_reservations_usecase)],
    user_id: str = _USER_ID_HEADER,
    status: ReservationStatus | None = Query(
        default=None, description="이 상태의 예약만 남긴다. 비우면 전체"
    ),
) -> list[ReservationResponse]:
    """내 예약 목록 — 최신순. `status`가 enum 밖이면 검증 계층이 400을 낸다."""
    results = usecase.execute(user_id=user_id, status=status)
    return [_to_response(result) for result in results]


@router.get(
    "/reservations/{confirmation_code}",
    response_model=ReservationResponse,
    summary="예약 단건 조회",
)
def get_reservation(
    confirmation_code: str,
    usecase: Annotated[GetReservationUseCase, Depends(deps.get_reservation_usecase)],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """확정 코드로 내 예약 하나를 조회한다. 남의 예약이면 404다."""
    result = usecase.execute(confirmation_code=confirmation_code, user_id=user_id)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/confirm",
    response_model=ReservationResponse,
    summary="예약 확정 (모의 결제)",
)
def confirm_reservation(
    confirmation_code: str,
    usecase: Annotated[
        ConfirmReservationUseCase, Depends(deps.confirm_reservation_usecase)
    ],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """PENDING 예약을 결제 승인 뒤 CONFIRMED로 전이한다.

    결제 호출은 DB 트랜잭션 밖에서 일어난다 (제출 문서 3.4절). 이미 만료·취소된
    예약이면 409 `INVALID_STATE_TRANSITION`이다.
    """
    result = usecase.execute(confirmation_code=confirmation_code, user_id=user_id)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/cancel",
    response_model=ReservationResponse,
    summary="예약 취소",
)
def cancel_reservation(
    confirmation_code: str,
    usecase: Annotated[
        CancelReservationUseCase, Depends(deps.cancel_reservation_usecase)
    ],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """예약을 CANCELLED로 전이하고 재고를 복원한다.

    이미 취소된 예약에 또 오면 성공으로 응답하되 아무것도 바꾸지 않는다
    (멱등 흡수) — 재고를 두 번 돌려놓지 않는다.
    """
    result = usecase.execute(confirmation_code=confirmation_code, user_id=user_id)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/check-in",
    response_model=ReservationResponse,
    summary="체크인",
)
def check_in(
    confirmation_code: str,
    usecase: Annotated[CheckInOutUseCase, Depends(deps.check_in_out_usecase)],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """CONFIRMED 예약을 CHECKED_IN으로 전이한다."""
    result = usecase.check_in(confirmation_code=confirmation_code)
    return _to_response(result)


@router.post(
    "/reservations/{confirmation_code}/check-out",
    response_model=ReservationResponse,
    summary="체크아웃",
)
def check_out(
    confirmation_code: str,
    usecase: Annotated[CheckInOutUseCase, Depends(deps.check_in_out_usecase)],
    user_id: str = _USER_ID_HEADER,
) -> ReservationResponse:
    """CHECKED_IN 예약을 CHECKED_OUT으로 전이한다."""
    result = usecase.check_out(confirmation_code=confirmation_code)
    return _to_response(result)


@router.post(
    "/internal/reservations/expire",
    response_model=ExpireResponse,
    summary="미결제 만료 배치 (수동 트리거)",
)
def expire_reservations(
    usecase: Annotated[
        ExpireReservationsUseCase, Depends(deps.expire_reservations_usecase)
    ],
) -> ExpireResponse:
    """수동 트리거 — 테스트·부하테스트는 주기를 기다릴 수 없다 (2.5절).

    평상시에는 30초 주기의 배경 스캐너가 같은 유스케이스를 돌린다.
    """
    expired = usecase.execute()
    return ExpireResponse(expired_count=expired)
