"""모의 결제 규약 (스펙 2.3절 표) — 3회차 리뷰 소급분.

구현이 테스트보다 먼저 커밋된 절대 규칙 위반을 소급으로 닫는다.
declined 분기 두 줄을 맞바꿔도 잡는 테스트가 없었다.
"""

from app.reservation.infrastructure.payment import FakePaymentAdapter


def test_기본_거절률_0은_항상_승인이다():
    """모의 결제 — 거절률 0이면 100번 청구가 전부 승인이다. 승인 건은 거래
    id가 있고 거절 사유는 없다."""
    adapter = FakePaymentAdapter(decline_rate=0.0)
    for _ in range(100):
        result = adapter.charge(reservation_id=1, amount=450000, idempotency_key="k")
        assert result.approved is True
        assert result.transaction_id is not None
        assert result.decline_reason is None


def test_거절률_1은_항상_거절이다():
    """모의 결제 — 거절률 1이면 100번 청구가 전부 거절이다. 거절 건은 거래
    id가 없고 사유는 PAYMENT_DECLINED 하나뿐이다(2.3절). 승인·거절 분기 두
    줄을 맞바꾸는 회귀를 잡는다."""
    adapter = FakePaymentAdapter(decline_rate=1.0)
    for _ in range(100):
        result = adapter.charge(reservation_id=1, amount=450000, idempotency_key="k")
        assert result.approved is False
        assert result.transaction_id is None
        # 거절 사유는 PAYMENT_DECLINED 한 가지다 (2.3절)
        assert result.decline_reason == "PAYMENT_DECLINED"


def test_거절은_예외가_아니라_반환값이다():
    """모의 결제(계약) — 거절은 예외가 아니라 approved=False 반환이다. 예외로
    던지면 정상 거절과 진짜 장애의 구분이 사라진다."""
    # 예외로 던지면 진짜 장애와 구분이 사라진다 — charge는 던지지 않는다
    adapter = FakePaymentAdapter(decline_rate=1.0)
    result = adapter.charge(reservation_id=1, amount=0, idempotency_key="k")
    assert result.approved is False  # 예외 없이 여기 도달하는 것 자체가 검증이다
