"""모의 결제 규약 (스펙 2.3절 표) — 3회차 리뷰 소급분.

구현이 테스트보다 먼저 커밋된 절대 규칙 위반을 소급으로 닫는다.
declined 분기 두 줄을 맞바꿔도 잡는 테스트가 없었다.
"""

from app.reservation.infrastructure.payment import FakePaymentAdapter


def test_기본_거절률_0은_항상_승인이다():
    adapter = FakePaymentAdapter(decline_rate=0.0)
    for _ in range(100):
        result = adapter.charge(reservation_id=1, amount=450000, idempotency_key="k")
        assert result.approved is True
        assert result.transaction_id is not None
        assert result.decline_reason is None


def test_거절률_1은_항상_거절이다():
    adapter = FakePaymentAdapter(decline_rate=1.0)
    for _ in range(100):
        result = adapter.charge(reservation_id=1, amount=450000, idempotency_key="k")
        assert result.approved is False
        assert result.transaction_id is None
        # 거절 사유는 PAYMENT_DECLINED 한 가지다 (2.3절)
        assert result.decline_reason == "PAYMENT_DECLINED"


def test_거절은_예외가_아니라_반환값이다():
    # 예외로 던지면 진짜 장애와 구분이 사라진다 — charge는 던지지 않는다
    adapter = FakePaymentAdapter(decline_rate=1.0)
    result = adapter.charge(reservation_id=1, amount=0, idempotency_key="k")
    assert result.approved is False  # 예외 없이 여기 도달하는 것 자체가 검증이다
