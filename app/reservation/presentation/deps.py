"""예약 라우터의 의존 제공자 (ADR-0064).

**엔드포인트는 의존을 서명에 선언하고, 컨테이너를 찾아가는 코드는 이 파일
하나에만 있다.** 전에는 엔드포인트 12곳이 각자 `request.app.state.container...`
로 컨테이너를 뒤졌다 — 조립은 컨테이너가 하는데 주입이 없어서, 사실상
서비스 로케이터였다.

`dependency_injector`의 `@inject`+`Provide[...]` 배선을 쓰지 않은 이유:
그 배선은 **프로세스 전역**이라 마지막으로 wire한 컨테이너가 이긴다.
이 프로젝트는 앱 팩토리다 — actuator 테스트가 환경을 바꾼 앱을 도중에
만들면, 세션 앱의 주입이 그 컨테이너로 바뀌어 버린다. 앱마다 자기
컨테이너를 쓰는 격리가 테스트의 전제라서, FastAPI의 요청 단위 해석으로
같은 목표(서명 선언·로케이터 제거)를 얻는다.
"""

from fastapi import Request

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


def create_reservation_usecase(request: Request) -> CreateReservationUseCase:
    return request.app.state.container.reservation.create_reservation()


def list_reservations_usecase(request: Request) -> ListReservationsUseCase:
    return request.app.state.container.reservation.list_reservations()


def get_reservation_usecase(request: Request) -> GetReservationUseCase:
    return request.app.state.container.reservation.get_reservation()


def confirm_reservation_usecase(request: Request) -> ConfirmReservationUseCase:
    return request.app.state.container.reservation.confirm_reservation()


def cancel_reservation_usecase(request: Request) -> CancelReservationUseCase:
    return request.app.state.container.reservation.cancel_reservation()


def check_in_out_usecase(request: Request) -> CheckInOutUseCase:
    return request.app.state.container.reservation.check_in_out()


def expire_reservations_usecase(request: Request) -> ExpireReservationsUseCase:
    return request.app.state.container.reservation.expire_reservations()
