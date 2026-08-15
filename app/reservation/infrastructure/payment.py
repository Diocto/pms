"""모의 결제 (스펙 2.3절).

**거절은 예외가 아니라 반환값이다.** 예약은 그때 CANCELLED로 간다.
예외로 던지면 진짜 장애(네트워크 끊김)와 구분이 사라진다.

**가짜 구현은 결정적이어야 한다.** 기본 거절률 0.0(항상 승인)·1.0(항상 거절)은
결정적이고, 그 사이 값은 확률적이라 자동 테스트에서 쓰지 않는다 — 기본이
확률적이면 테스트가 가끔 깨지는데 원인이 경합인지 결제인지 구분되지 않는다.

실제 PG를 붙일 때 바뀌는 것은 이 어댑터 하나와 컨테이너 한 줄이다.
"""

import random
import uuid

from app.reservation.application.ports import PaymentResult


class FakePaymentAdapter:
    def __init__(self, decline_rate: float) -> None:
        self._decline_rate = decline_rate
        self.charged: list[int] = []           # 호출 관찰용 — "결제를 부르지
        self.refunded: list[str | None] = []   # 않는다"는 계약의 검증 수단이다

    def charge(
        self, *, reservation_id: int, amount: int, idempotency_key: str
    ) -> PaymentResult:
        self.charged.append(reservation_id)
        if self._decline_rate >= 1.0:
            declined = True          # 결정적 — 결제 실패 분기 전용 회차
        elif self._decline_rate <= 0.0:
            declined = False         # 결정적 — 기본값
        else:
            declined = random.random() < self._decline_rate  # 로컬 시연용. 테스트 금지

        if declined:
            return PaymentResult(approved=False, decline_reason="PAYMENT_DECLINED")
        return PaymentResult(approved=True, transaction_id=uuid.uuid4().hex)

    def refund(self, *, transaction_id: str | None) -> None:
        """모의 환불 — 기록만 한다. 실 PG라면 결제 취소 API 호출이다."""
        self.refunded.append(transaction_id)
