"""검색 결과 캐시 어댑터 (스펙 7절, D5·D7).

켜면 Redis, 끄면 NoOp — 선택은 컨테이너가 설정으로 한다 (D15).
캐시는 절단 1순위(00 D4)라, NoOp만으로도 시스템 전체가 돌아야 한다.
"""

import redis

from app.inventory.query.application.commands import AvailableRoomsResult


class NoOpAvailabilityCacheAdapter:
    """캐시 끔. 항상 미스이고 적재는 버린다 — 유스케이스는 차이를 모른다."""

    def get(self, key: str) -> AvailableRoomsResult | None:
        return None

    def put(self, key: str, result: AvailableRoomsResult) -> None:
        return None

    def evict_hotel(self, hotel_id: int) -> None:
        return None


class RedisAvailabilityCacheAdapter:
    """캐시 켬. 구현은 T7(TDD 15~17)에서 빨간 테스트로 채운다.

    그때까지 모든 메서드는 실패한다 — 유스케이스가 fail-open(D7)이라
    검색은 DB 직행으로 동작하고, WARN 로그가 미구현을 드러낸다.
    """

    def __init__(self, redis_client: redis.Redis, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def get(self, key: str) -> AvailableRoomsResult | None:
        raise NotImplementedError("T7에서 구현한다 (TDD 15~17)")

    def put(self, key: str, result: AvailableRoomsResult) -> None:
        raise NotImplementedError("T7에서 구현한다 (TDD 15~17)")

    def evict_hotel(self, hotel_id: int) -> None:
        raise NotImplementedError("T7에서 구현한다 (TDD 15~17)")
