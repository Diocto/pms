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
    """락 어댑터(기본 계약) — 키 3개를 묶음으로 잡으면 블록 안에서 셋 다 잠겨
    있고(exists 3), 블록을 나가면 전부 풀린다(exists 0)."""
    with adapter.acquire_all([KEY_B, KEY_A, KEY_C], wait_s=0.5, ttl_s=3):
        # 블록 안 — 셋 다 잠겨 있다
        assert redis_client.exists(KEY_A, KEY_B, KEY_C) == 3
    # 블록 밖 — 전부 풀렸다
    assert redis_client.exists(KEY_A, KEY_B, KEY_C) == 0


def test_하나가_막히면_이미_잡은_것을_풀고_503이다(adapter, redis_client):
    """락 어댑터(부분 실패 정리) — 우리 vs 가운데 키를 쥔 남. 세 키 중 하나가
    막히면 LockAcquisitionError(503)를 던지고, 이미 잡아둔 앞 키를 되돌려
    부분 획득 상태를 남기지 않는다."""
    redis_client.set(KEY_B, "someone-else")  # 가운데 키를 남이 쥐고 있다
    with pytest.raises(LockAcquisitionError):
        with adapter.acquire_all([KEY_A, KEY_B, KEY_C], wait_s=0.2, ttl_s=3):
            pytest.fail("여기 들어오면 부분 획득 상태로 진행한 것이다")
    # 먼저 잡았던 A가 풀려 있어야 한다 — 부분 실패 정리
    assert redis_client.exists(KEY_A) == 0
    assert redis_client.exists(KEY_C) == 0


def test_대기_상한은_키마다가_아니라_전체에_한_번이다(adapter, redis_client):
    """락 어댑터(전체 대기 상한, 실측) — 마지막 키를 남이 쥐고 있을 때 전체
    대기가 wait_s(0.3초)의 2배 미만에 끝난다. 상한이 키마다 곱해지지 않는다."""
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
    """락 어댑터 경합(락 레벨 K8) — 10스레드가 [B,A]와 [A,B]를 절반씩 반대
    순서로 잡아도 전원(10)이 완주한다. 정렬이 구현 안에 있다는 것의 경합 증명
    (4.2절 3회차 기준) — 정렬이 없으면 서로 물려 여기 못 온다."""
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
    """락 어댑터(중복 제거) — 같은 키를 세 번 넘겨도 실제로는 한 번만 잡는다.
    중복 제거가 없으면 두 번째 획득이 자기 자신에게 막혀 데드락이 된다."""
    with adapter.acquire_all([KEY_A, KEY_A, KEY_A], wait_s=0.5, ttl_s=3):
        assert redis_client.exists(KEY_A) == 1
    assert redis_client.exists(KEY_A) == 0


def test_TTL이_걸려_있어_프로세스가_죽어도_스스로_풀린다(adapter, redis_client):
    """락 어댑터(TTL) — 잡은 키에 TTL(3초 이하)이 걸려 있다. 해제 코드가 못
    도는 프로세스 급사에도 락이 영구히 남지 않는다."""
    with adapter.acquire_all([KEY_A], wait_s=0.5, ttl_s=3):
        ttl = redis_client.pttl(KEY_A)
        assert 0 < ttl <= 3000


def test_NoOp은_아무것도_잠그지_않고_통과한다(redis_client):
    """락 어댑터(NoOp 판) — 락을 끈 구성은 Redis에 키를 하나도 만들지 않고
    그대로 통과한다. K2(락 없이 2층 방어 단독) 시나리오의 전제 부품이다."""
    adapter = NoOpLockAdapter()
    with adapter.acquire_all([KEY_A, KEY_B], wait_s=0.5, ttl_s=3):
        assert redis_client.exists(KEY_A, KEY_B) == 0  # Redis에 아무 일도 없다


def test_대기_상한은_앞선_획득이_소모한_시간만큼_줄어든다(monkeypatch):
    """락 어댑터(전체 대기 상한, 가짜 시계) — 키마다 상한을 그대로 주는 회귀를
    잡는 판별력 보강(3회차 리뷰). 획득마다 0.1초를 소모시키면 blocking_timeout이
    0.5 → 0.4 → 0.3으로 줄어야 한다.

    실측 판(위)은 마지막 키 하나만 막힌 시나리오라 잘못된 구현도 통과한다.
    가짜 시계로 앞선 획득이 시간을 소모하게 만들고, 뒤 키의 blocking_timeout이
    소모분만큼 줄어드는지를 직접 본다.
    """
    import app.reservation.infrastructure.lock as lock_module

    clock = {"now": 100.0}
    monkeypatch.setattr(lock_module.time, "monotonic", lambda: clock["now"])
    recorded: list[tuple[str, float]] = []

    class RecordingLock:
        def __init__(self, key: str, blocking_timeout: float) -> None:
            self.name = key
            recorded.append((key, blocking_timeout))

        def acquire(self) -> bool:
            clock["now"] += 0.1  # 획득마다 0.1초를 소모한다
            return True

        def release(self) -> None:
            pass

    class RecordingRedis:
        def lock(self, key, timeout, blocking_timeout, sleep):  # noqa: ANN001
            return RecordingLock(key, blocking_timeout)

    adapter = RedisLockAdapter(RecordingRedis())
    with adapter.acquire_all([KEY_C, KEY_A, KEY_B], wait_s=0.5, ttl_s=3):
        pass

    keys = [key for key, _ in recorded]
    timeouts = [timeout for _, timeout in recorded]
    assert keys == sorted([KEY_A, KEY_B, KEY_C])  # 정렬도 함께 확인된다
    assert timeouts[0] == pytest.approx(0.5)
    assert timeouts[1] == pytest.approx(0.4)   # 키마다 wait_s면 전부 0.5라 여기서 잡힌다
    assert timeouts[2] == pytest.approx(0.3)
