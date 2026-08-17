"""검색 라우터의 의존 제공자 (ADR-0064).

컨테이너를 찾아가는 코드는 이 파일에만 있다. 이유는
`app/reservation/presentation/deps.py`의 모듈 주석과 같다.
"""

from fastapi import Request

from app.inventory.query.application.usecases.list_hotels import ListHotelsUseCase
from app.inventory.query.application.usecases.search_available_rooms import (
    SearchAvailableRoomsUseCase,
)


def list_hotels_usecase(request: Request) -> ListHotelsUseCase:
    return request.app.state.container.inventory_query.list_hotels()


def search_available_rooms_usecase(request: Request) -> SearchAvailableRoomsUseCase:
    return request.app.state.container.inventory_query.search_available_rooms()
