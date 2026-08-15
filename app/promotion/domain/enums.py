"""사용권 상태와 이벤트 (스펙 4절).

**이름과 값을 같은 대문자 문자열로 둔다.** DB에 어느 쪽으로 저장되든 같은
문자열이 되게 하기 위해서다. 값이 다르면 F04의 검증 SQL(`WHERE status =
'RELEASED'`)이 0행을 돌려주고 모든 검증이 통과로 보인다 — 깨진 게 아니라
아무것도 안 본 것인데 초록불이 켜진다. `ck_claim_released` CHECK도 같은
문자열에 의존한다 (스펙 §4, T36).

상태가 둘뿐인 이유 — 예약이 먼저 만들어지고 같은 트랜잭션에서 사용권이
생기므로(C4) "재고는 잡았는데 예약은 아직"인 중간 상태가 존재하지 않는다.
"""

from enum import Enum


class ClaimStatus(str, Enum):
    USED = "USED"          # 태어날 때부터 예약에 붙어 있다
    RELEASED = "RELEASED"  # 종료 — 예약 취소·만료로 반납됨


class ClaimEvent(str, Enum):
    RELEASE = "RELEASE"    # 반납. 예약의 CANCEL·PAYMENT_FAILED·EXPIRE에서 온다
