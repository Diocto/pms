"""분산락 — `redis-py`의 `Lock` 위에 얹은 `acquire_all` (스펙 3.3절, D10).

락 하나의 원자성(SET NX PX·토큰·Lua 해제)은 라이브러리 몫이고, 여기서
검증하는 것은 **우리가 직접 쓴 묶음 처리**다 — 정렬, 전체 대기 상한,
부분 실패 정리, 역순 해제.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis as redis_library

from app.reservation.application.errors import LockAcquisitionError
from app.reservation.infrastructure.lock import NoOpLockAdapter, RedisLockAdapter

KEY_A = "lock:inventory:1:2026-09-01"
KEY_B = "lock:inventory:1:2026-09-02"
KEY_C = "lock:inventory:1:2026-09-03"


@pytest.fixture(scope="module")
def redis_client(redis_url):
    client = redis_library.Redis.from_url(redis_url)
    yield client
    client.close()


@pytest.fixture()
def adapter(redis_client):
    redis_client.flushdb()
    return RedisLockAdapter(redis_client)


def test_전부_잡고_전부_푼다(adapter, redis_client):
    with adapter.acquire_all([KEY_B, KEY_A, KEY_C], wait_s=0.5, ttl_s=3):
        # 블록 안 — 셋 다 잠겨 있다
        assert redis_client.exists(KEY_A, KEY_B, KEY_C) == 3
    # 블록 밖 — 전부 풀렸다
    assert redis_client.exists(KEY_A, KEY_B, KEY_C) == 0


def test_하나가_막히면_이미_잡은_것을_풀고_503이다(adapter, redis_client):
    redis_client.set(KEY_B, "someone-else")  # 가운데 키를 남이 쥐고 있다
    with pytest.raises(LockAcquisitionError):
        with adapter.acquire_all([KEY_A, KEY_B, KEY_C], wait_s=0.2, ttl_s=3):
            pytest.fail("여기 들어오면 부분 획득 상태로 진행한 것이다")
    # 먼저 잡았던 A가 풀려 있어야 한다 — 부분 실패 정리
    assert redis_client.exists(KEY_A) == 0
    assert redis_client.exists(KEY_C) == 0


def test_대기_상한은_키마다가_아니라_전체에_한_번이다(adapter, redis_client):
    # 세 키 중 마지막을 남이 쥐고 있다. 키마다 상한을 주면 최대 3배를 기다린다
    redis_client.set(KEY_C, "someone-else")
    wait_s = 0.3
    started = time.monotonic()
    with pytest.raises(LockAcquisitionError):
        with adapter.acquire_all([KEY_A, KEY_B, KEY_C], wait_s=wait_s, ttl_s=3):
            pass
    elapsed = time.monotonic() - started
    assert elapsed < wait_s * 2, (
        f"전체 대기가 {elapsed:.2f}s — 상한이 키마다 적용된 것으로 보인다"
    )


def test_겹치는_키를_반대_순서로_넣어도_서로_물리지_않는다(adapter):
    """정렬이 구현 안에 있다는 것의 경합 증명 (락 레벨 K8, 4.2절 3회차 기준)."""
    threads = 10
    barrier = threading.Barrier(threads)
    completed = 0
    unexpected: list[Exception] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        nonlocal completed
        keys = [KEY_B, KEY_A] if index % 2 == 0 else [KEY_A, KEY_B]
        try:
            barrier.wait()
            with adapter.acquire_all(keys, wait_s=5.0, ttl_s=3):
                pass
            with lock:
                completed += 1
        except Exception as error:  # noqa: BLE001
            with lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(attempt, index) for index in range(threads)]
    for future in futures:
        future.result()

    assert unexpected == [], f"예상 못 한 예외: {unexpected[:3]}"
    assert completed == threads  # 정렬이 없으면 서로 물려 여기 못 온다


def test_중복_키는_한_번만_잡는다(adapter, redis_client):
    with adapter.acquire_all([KEY_A, KEY_A, KEY_A], wait_s=0.5, ttl_s=3):
        assert redis_client.exists(KEY_A) == 1
    assert redis_client.exists(KEY_A) == 0


def test_TTL이_걸려_있어_프로세스가_죽어도_스스로_풀린다(adapter, redis_client):
    with adapter.acquire_all([KEY_A], wait_s=0.5, ttl_s=3):
        ttl = redis_client.pttl(KEY_A)
        assert 0 < ttl <= 3000


def test_NoOp은_아무것도_잠그지_않고_통과한다(redis_client):
    adapter = NoOpLockAdapter()
    with adapter.acquire_all([KEY_A, KEY_B], wait_s=0.5, ttl_s=3):
        assert redis_client.exists(KEY_A, KEY_B) == 0  # Redis에 아무 일도 없다
