"""promotion 컨텍스트의 도메인 예외.

`code`가 클라이언트와의 계약이다 — `app/common/error_codes.py`에 등록된
문자열만 나갈 수 있고, 계약 테스트(`test_error_contract.py`)가 대조한다.
"""

from app.common.errors import ConflictError


class PromotionNotOpenError(ConflictError):
    """판매 창 밖이다. 잘못된 요청이 아니라 기다렸다 다시 보내면 되는
    요청이라 400이 아니라 409다 (스펙 §8, D12)."""

    code = "PROMOTION_NOT_OPEN"


class PromotionSoldOutError(ConflictError):
    """잔여가 없다. 매진 판정의 권한은 생성 훅의 조건부 UPDATE 한 곳에 있고
    (스펙 §6), 도메인 메서드의 이 예외는 같은 판정의 객체 수준 표현이다."""

    code = "PROMOTION_SOLD_OUT"


class DuplicateReleaseError(ConflictError):
    """이미 반납된 특가를 또 되돌리려 했다. HTTP로 나갈 일이 없는 예외다 —
    반납 훅은 전이 조건부 UPDATE 0건으로 이 경우를 조용히 멱등 처리하고(스펙
    §6), 이 예외는 도메인 객체를 직접 다루는 코드의 방어선이다. 그래도
    코드는 계약 안에 있어야 하므로 상태 전이 위반으로 분류한다."""

    code = "INVALID_STATE_TRANSITION"
