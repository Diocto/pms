"""멱등성 저장소 — Redis `SET NX` (스펙 3.4절).

키는 `idem:reservation:{userId}:{key}`로 **사용자와 조합한다.** 조합하지
않으면 다른 사용자가 같은 키 문자열을 보냈을 때 남의 예약 결과를 받는다.

값은 `PROCESSING` 또는 `DONE:{confirmationCode}`. Redis가 죽으면 이 계층이
통째로 무력화되지만 DB의 `UNIQUE(user_id, idempotency_key)`가 정답을 지킨다 —
**Redis는 빠른 길이고 DB 제약이 정답이다.**
"""

import redis

from app.reservation.application.ports import IdempotencyClaim

_PROCESSING = "PROCESSING"
_DONE_PREFIX = "DONE:"
_FAILED_PREFIX = "FAILED:"


def _key(user_id: str, key: str) -> str:
    return f"idem:reservation:{user_id}:{key}"


class RedisIdempotencyAdapter:
    def __init__(self, client: redis.Redis) -> None:
        self._redis = client

    def claim(self, *, user_id: str, key: str, ttl_seconds: int) -> IdempotencyClaim:
        acquired = self._redis.set(
            _key(user_id, key), _PROCESSING, nx=True, ex=ttl_seconds
        )
        if acquired:
            return IdempotencyClaim(outcome="acquired")

        value = self._redis.get(_key(user_id, key))
        if value is None:
            # 선점 실패와 조회 사이에 TTL이 끝났다. 재시도 없이 최초로 취급하면
            # 두 요청이 같이 진행될 수 있으므로 처리 중으로 보수적으로 답한다.
            # 진짜 중복은 DB UK가 막는다
            return IdempotencyClaim(outcome="processing")
        if isinstance(value, bytes):
            value = value.decode()
        if value.startswith(_DONE_PREFIX):
            return IdempotencyClaim(
                outcome="done", confirmation_code=value[len(_DONE_PREFIX):]
            )
        if value.startswith(_FAILED_PREFIX):
            # 실패로 완료된 키 — 같은 키 재요청은 같은 에러 코드를 받는다 (D30).
            # PROCESSING으로 남겨두면 재요청이 REQUEST_IN_PROGRESS로 둔갑한다
            return IdempotencyClaim(
                outcome="failed", failure_code=value[len(_FAILED_PREFIX):]
            )
        return IdempotencyClaim(outcome="processing")

    def store(
        self, *, user_id: str, key: str, confirmation_code: str, ttl_seconds: int
    ) -> None:
        self._redis.set(
            _key(user_id, key), f"{_DONE_PREFIX}{confirmation_code}", ex=ttl_seconds
        )

    def store_failure(
        self, *, user_id: str, key: str, failure_code: str, ttl_seconds: int
    ) -> None:
        self._redis.set(
            _key(user_id, key), f"{_FAILED_PREFIX}{failure_code}", ex=ttl_seconds
        )

    def release(self, *, user_id: str, key: str) -> None:
        self._redis.delete(_key(user_id, key))
