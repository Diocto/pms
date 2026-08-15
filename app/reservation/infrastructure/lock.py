"""분산락 — `redis-py`의 `Lock` 위에 묶음 처리만 얹는다 (스펙 3.3절, D10).

`SET NX PX`·획득마다 고유 토큰·Lua 비교 삭제·대기 상한은 **라이브러리에 이미
있다.** 직접 쓰면 검증되지 않은 코드가 하나 더 생기고, 락은 평소에 정상으로
보이고 경합이 몰릴 때만 깨지므로 틀리면 조용히 틀린다.

우리 몫은 여러 키를 한 묶음으로 다루는 부분뿐이다 — 정렬, 전체 대기 상한,
부분 실패 정리, 역순 해제.

**락은 정확성을 책임지지 않는다** — 초과 판매를 막는 것은 2층 조건부 UPDATE다.
그래서 Redlock도, 워치독 TTL 연장도 쓰지 않는다. TTL이 트랜잭션보다 먼저
끝나도 데이터는 안 깨지고 느려질 뿐이다.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

import redis
from redis.exceptions import LockNotOwnedError
from redis.lock import Lock

from app.reservation.application.errors import LockAcquisitionError

logger = logging.getLogger(__name__)


class RedisLockAdapter:
    def __init__(self, client: redis.Redis) -> None:
        self._redis = client

    @contextmanager
    def acquire_all(
        self, keys: list[str], *, wait_s: float, ttl_s: int
    ) -> Iterator[None]:
        ordered = sorted(set(keys))            # ← 정렬·중복 제거가 여기서만 일어난다
        deadline = time.monotonic() + wait_s   # ← 대기 상한은 전체에 한 번
        held: list[Lock] = []
        try:
            for key in ordered:
                remaining = deadline - time.monotonic()
                lock = self._redis.lock(
                    key,
                    timeout=ttl_s,
                    blocking_timeout=max(remaining, 0),
                    sleep=0.01,
                )
                if not lock.acquire():
                    # 부하테스트 결과 해석의 근거가 되는 로그 (coding-rules.md)
                    logger.info("락 획득 실패 key=%s wait_s=%s", key, wait_s)
                    raise LockAcquisitionError(
                        "혼잡으로 요청을 처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요"
                    )
                held.append(lock)
            yield                              # ← 전부 잡은 뒤에야 호출부로 넘어간다
        finally:
            for lock in reversed(held):        # ← 역순 해제. 중간 실패에도 잡은 것은 푼다
                try:
                    lock.release()
                except LockNotOwnedError:
                    # "내가 잡은 락이 이미 만료돼 남이 가져갔다" — TTL이
                    # 트랜잭션보다 짧다는 신호다. 삼키지 않고 기록한다
                    logger.warning("락이 이미 만료됐다 key=%s ttl_s=%s", lock.name, ttl_s)


class NoOpLockAdapter:
    """`PMS_LOCK_ENABLED=false`의 구현 — 아무것도 잠그지 않는다.

    이것이 다층 방어의 증명 수단이다. 락을 끄고 같은 부하를 돌려 불변식이
    그대로면(K2), 정확성이 2·3층에 있다는 것이 실험으로 증명된다.
    """

    @contextmanager
    def acquire_all(
        self, keys: list[str], *, wait_s: float, ttl_s: int
    ) -> Iterator[None]:
        yield
