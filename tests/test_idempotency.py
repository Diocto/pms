"""멱등성 저장소 — Redis `SET NX` (스펙 3.4절, D9·D18).

Redis는 빠른 길이고 DB UK가 정답이다. 여기서는 빠른 길의 계약을 고정한다:
최초/처리 중/완료의 3상태, 사용자별 격리, 입력 오류 시 삭제·재고 부족 시 유지.
"""

import pytest
import redis as redis_library

from app.reservation.infrastructure.idempotency import RedisIdempotencyAdapter

TTL = 600


@pytest.fixture(scope="module")
def redis_client(redis_url):
    # 프로덕션 컨테이너와 같은 decode_responses=False다 — 테스트가 str 경로만
    # 돌면 실제로 실행되는 bytes 분기가 한 번도 검증되지 않는다 (3회차 리뷰)
    client = redis_library.Redis.from_url(redis_url, decode_responses=False)
    yield client
    client.close()


@pytest.fixture()
def adapter(redis_client):
    redis_client.flushdb()
    return RedisIdempotencyAdapter(redis_client)


def test_최초_요청은_선점에_성공한다(adapter):
    claim = adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    assert claim.outcome == "acquired"


def test_처리_중_재요청은_processing이다(adapter):
    adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    claim = adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    assert claim.outcome == "processing"
    assert claim.confirmation_code is None


def test_완료_후_재요청은_저장된_결과를_돌려준다(adapter):
    adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    adapter.store(
        user_id="user-1", key="k-1", confirmation_code="260901-H1R1-ABCDEFGH",
        ttl_seconds=TTL,
    )
    claim = adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    assert claim.outcome == "done"
    assert claim.confirmation_code == "260901-H1R1-ABCDEFGH"


def test_다른_사용자는_같은_키_문자열을_써도_간섭하지_않는다(adapter):
    # 조합하지 않으면 남의 예약 결과를 받는다 (3.4절)
    adapter.claim(user_id="user-1", key="shared", ttl_seconds=TTL)
    adapter.store(
        user_id="user-1", key="shared", confirmation_code="CODE-A", ttl_seconds=TTL
    )
    claim = adapter.claim(user_id="user-2", key="shared", ttl_seconds=TTL)
    assert claim.outcome == "acquired"  # user-2에게는 최초 요청이다


def test_release는_키를_지워_같은_키_재시도를_최초로_만든다(adapter):
    # 입력 오류(400)로 실패하면 키를 지운다 — 고쳐서 다시 보내는 것이 정상이다
    adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    adapter.release(user_id="user-1", key="k-1")
    claim = adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    assert claim.outcome == "acquired"


def test_선점_키에_TTL이_걸려_있다(adapter, redis_client):
    adapter.claim(user_id="user-1", key="k-1", ttl_seconds=TTL)
    ttl = redis_client.ttl("idem:reservation:user-1:k-1")
    assert 0 < ttl <= TTL  # TTL 없는 키는 Redis에 영구히 남는다


def test_store는_TTL을_갱신한다(adapter, redis_client):
    adapter.claim(user_id="user-1", key="k-1", ttl_seconds=30)
    adapter.store(
        user_id="user-1", key="k-1", confirmation_code="CODE", ttl_seconds=TTL
    )
    ttl = redis_client.ttl("idem:reservation:user-1:k-1")
    assert 30 < ttl <= TTL


def test_동시_선점은_정확히_하나만_acquired다(adapter, redis_client):
    """멱등성의 존재 이유인 경합을 직접 검증한다 (3회차 리뷰).

    claim을 비원자 구성(GET 후 SET)으로 바꾸는 회귀가 생기면 여기서 잡힌다 —
    순차 테스트는 그 회귀에도 전부 초록이다.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    threads = 30
    barrier = threading.Barrier(threads)
    outcomes: list[str] = []
    unexpected: list[Exception] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait()
            claim = adapter.claim(user_id="user-conc", key="k-conc", ttl_seconds=TTL)
            with lock:
                outcomes.append(claim.outcome)
        except Exception as error:  # noqa: BLE001
            with lock:
                unexpected.append(error)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(attempt) for _ in range(threads)]
    for future in futures:
        future.result()

    assert unexpected == []
    assert outcomes.count("acquired") == 1
    assert outcomes.count("processing") == threads - 1
    assert redis_client.get("idem:reservation:user-conc:k-conc") == b"PROCESSING"


def test_실패_완료는_같은_에러_코드를_다시_받는다(adapter):
    """D30 — 재고 부족을 PROCESSING으로 남기면 재요청이 REQUEST_IN_PROGRESS로
    둔갑한다. 실패도 결과다 — 같은 키 재요청은 같은 409를 받아야 한다 (D18)."""
    adapter.claim(user_id="user-1", key="k-fail", ttl_seconds=TTL)
    adapter.store_failure(
        user_id="user-1", key="k-fail",
        failure_code="INSUFFICIENT_INVENTORY", ttl_seconds=TTL,
    )
    claim = adapter.claim(user_id="user-1", key="k-fail", ttl_seconds=TTL)
    assert claim.outcome == "failed"
    assert claim.failure_code == "INSUFFICIENT_INVENTORY"
    assert claim.confirmation_code is None
