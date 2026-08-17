"""예약 상태와 이벤트 (스펙 1.4절).

**이름과 값을 같은 대문자 문자열로 둔다.** DB에 어느 쪽으로 저장되든 같은
문자열이 되게 하기 위해서다. 값이 이름과 다르면 부하테스트의 검증 SQL
(`WHERE event IN ('CANCEL', ...)`)이 0행을 돌려주고 **모든 불변식이 통과로
보인다** — 깨진 게 아니라 아무것도 안 본 것인데 초록불이 켜진다 (스펙 1.6절).
"""

from enum import Enum


class ReservationStatus(str, Enum):
    PENDING = "PENDING"          # 생성됨, 결제 대기. 재고는 이미 확보
    CONFIRMED = "CONFIRMED"      # 결제 완료
    CHECKED_IN = "CHECKED_IN"    # 투숙 중
    CHECKED_OUT = "CHECKED_OUT"  # 종료 — 정상 완료
    CANCELLED = "CANCELLED"      # 종료 — 취소·결제 실패
    EXPIRED = "EXPIRED"          # 종료 — 미결제 만료

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = frozenset(
    {
        ReservationStatus.CHECKED_OUT,
        ReservationStatus.CANCELLED,
        ReservationStatus.EXPIRED,
    }
)


class ReservationEvent(str, Enum):
    CONFIRM = "CONFIRM"                # 결제 성공
    PAYMENT_FAILED = "PAYMENT_FAILED"  # 결제 거절 (정상 흐름의 결과다, 2.3절)
    CANCEL = "CANCEL"                  # 사용자 취소
    EXPIRE = "EXPIRE"                  # 보류 시간 초과
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
