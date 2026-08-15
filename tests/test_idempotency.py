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
    client = redis_library.Redis.from_url(redis_url, decode_responses=True)
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
