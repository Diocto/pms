"""가용 객실 검색 유스케이스 (스펙 6절 UC-1).

경로는 셋이다: 캐시 히트(쿼리 0회), 미스(집계 1회), 빈 결과(집계+진단 2회).
Redis 왕복은 세션 `with` 블록 밖에 있다 (D12) — 들여쓰기가 곧 트랜잭션
범위라 이 규칙은 눈으로 확인된다. 캐시는 어느 쪽이 실패해도 검색을 막지
않는다 (D7 fail-open).
"""

import logging

from app.common.clock import Clock
from app.common.db import TransactionManager
from app.inventory.query.application.commands import (
    AvailableRoomsResult,
    EmptyReason,
    SearchAvailableRoomsQuery,
    Source,
)
from app.inventory.query.application.ports import (
    AvailabilityCachePort,
    AvailabilityQueryPort,
)

logger = logging.getLogger(__name__)


class SearchAvailableRoomsUseCase:
    def __init__(
        self,
        transaction_manager: TransactionManager,
        query_adapter: AvailabilityQueryPort,
        cache: AvailabilityCachePort,
        clock: Clock,
        stale_tolerance_seconds: int,
    ) -> None:
        self._tx = transaction_manager
        self._query_adapter = query_adapter
        self._cache = cache
        self._clock = clock
        self._stale_tolerance_seconds = stale_tolerance_seconds

    def execute(self, query: SearchAvailableRoomsQuery) -> AvailableRoomsResult:
        query.stay.ensure_not_past(today=self._clock.today())

        key = query.cache_key()
        if not query.fresh:
            cached = self._cache_get(key)
            if cached is not None:
                # searched_at은 저장 시각 그대로 둔다 — 응답 시각으로 덮으면
                # 캐시 히트인데도 방금 조회한 것처럼 보여 낡음이 숨겨진다 (I7)
                return cached.model_copy(update={"source": Source.CACHE})

        # 세션 수명은 DB 읽기로만 좁힌다. 정상 경로는 집계 1회,
        # 빈 결과일 때만 같은 스냅샷 안에서 진단 1회가 더 나간다
        with self._tx.read() as session:
            items = self._query_adapter.search(session, query)
            diagnosis = (
                None if items else self._query_adapter.diagnose(session, query)
            )

        if diagnosis is None:
            result = AvailableRoomsResult(
                searched_at=self._clock.now(),
                source=Source.DB,
                stale_tolerance_seconds=self._stale_tolerance_seconds,
                items=items,
            )
        else:
            reason = diagnosis.empty_reason(query.stay)  # 없는 호텔이면 404
            result = AvailableRoomsResult(
                searched_at=self._clock.now(),
                source=Source.DB,
                stale_tolerance_seconds=self._stale_tolerance_seconds,
                items=[],
                empty_reason=reason,
                sales_open_until=(
                    diagnosis.sales_open_until
                    if reason is EmptyReason.NOT_YET_OPEN
                    else None
                ),
            )

        # 빈 결과도 적재한다 — 매진 인기 날짜가 캐시를 우회하면 부하가 몰린다
        self._cache_put(key, result)
        return result

    def _cache_get(self, key: str) -> AvailableRoomsResult | None:
        try:
            return self._cache.get(key)
        except Exception:
            logger.warning("캐시 조회 실패 — DB로 진행한다 (key=%s)", key, exc_info=True)
            return None

    def _cache_put(self, key: str, result: AvailableRoomsResult) -> None:
        try:
            self._cache.put(key, result)
        except Exception:
            logger.warning("캐시 적재 실패 — 응답은 그대로 나간다 (key=%s)", key, exc_info=True)
