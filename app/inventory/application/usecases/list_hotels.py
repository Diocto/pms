"""호텔 목록 유스케이스 (관리자 지시 2026-08-16, 검색 화면용).

정적 마스터 조회 1발이라 캐시를 두지 않는다 — 시드 이후 바뀌지 않는
데이터에 캐시를 얹으면 무효화 경로만 하나 늘어난다.
"""

from app.inventory.application.commands import HotelView
from app.inventory.application.ports import HotelCatalogPort


class ListHotelsUseCase:
    def __init__(self, transaction_manager, catalog: HotelCatalogPort) -> None:
        self._tx = transaction_manager
        self._catalog = catalog

    def execute(self) -> list[HotelView]:
        with self._tx.read() as session:
            return self._catalog.list_hotels(session)
