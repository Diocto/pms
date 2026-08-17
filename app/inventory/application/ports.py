"""검색 유스케이스가 바깥에 요구하는 것 (스펙 3절).

포트 2개뿐이고 전부 Protocol이다. 구현은 `infrastructure`에 있고
컨테이너가 고른다 — 유스케이스는 무엇이 들어오는지 모른다.
"""

from typing import Protocol

from sqlalchemy.orm import Session

from app.inventory.application.commands import (
    AvailabilityDiagnosis,
    AvailableRoomsResult,
    AvailableRoomTypeView,
    HotelView,
    SearchAvailableRoomsQuery,
)


class AvailabilityQueryPort(Protocol):
    """집계·진단 쿼리. 세션은 유스케이스가 열어서 준다 — 구현이 스스로 열면
    트랜잭션이 둘로 갈라진다 (tdd.md의 세션 경계 테스트가 지킨다)."""

    def search(
        self, session: Session, query: SearchAvailableRoomsQuery
    ) -> list[AvailableRoomTypeView]: ...

    def diagnose(
        self, session: Session, query: SearchAvailableRoomsQuery
    ) -> AvailabilityDiagnosis: ...


class HotelCatalogPort(Protocol):
    """호텔·객실타입 마스터 목록. 세션은 유스케이스가 열어서 준다 —
    구현이 스스로 열면 트랜잭션이 둘로 갈라진다."""

    def list_hotels(self, session: Session) -> list[HotelView]:
        """전체 호텔을 id 오름차순으로, 객실타입은 그 안에서 id 오름차순으로."""
        ...


class AvailabilityCachePort(Protocol):
    """결과 스냅샷 캐시. 어느 메서드든 실패해도 검색은 계속돼야 한다 (D7 fail-open).

    `evict_hotel`은 자리만 있다 — 검색 프로덕션 코드는 부르지 않고,
    테스트(C3)와 운영 조작만 부른다 (D6).
    """

    def get(self, key: str) -> AvailableRoomsResult | None: ...

    def put(self, key: str, result: AvailableRoomsResult) -> None: ...

    def evict_hotel(self, hotel_id: int) -> None: ...
