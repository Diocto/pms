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
    """캐시 켬. 값은 결과 스냅샷의 JSON이고, `searched_at`이 값 안에 함께
    들어간다 — 히트 응답이 저장 시각을 그대로 내보내는 근거다 (I7).

    **`SET`에 만료를 반드시 함께 건다.** TTL이 빠지면 낡음의 상한이
    사라지고 스스로 회복되지 않는다 — 7절에서 유일하게 회복 불가인
    실패(I5)다. 히트 시 TTL을 연장하지도 않는다 (연장하면 인기 검색어일수록
    더 오래 낡는다).
    """

    def __init__(self, redis_client: redis.Redis, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def get(self, key: str) -> AvailableRoomsResult | None:
        value = self._redis.get(key)
        if value is None:
            return None
        return AvailableRoomsResult.model_validate_json(value)

    def put(self, key: str, result: AvailableRoomsResult) -> None:
        self._redis.set(key, result.model_dump_json(), ex=self._ttl_seconds)

    def evict_hotel(self, hotel_id: int) -> None:
        # 호텔 단위 키 설계(avail:{hotelId}:...)라 패턴 하나로 다 걷힌다.
        # KEYS는 전체 블로킹이라 안 쓴다 — SCAN으로 순회한다
        for key in self._redis.scan_iter(match=f"avail:{hotel_id}:*"):
            self._redis.delete(key)
