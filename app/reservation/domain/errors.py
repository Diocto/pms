"""reservation 컨텍스트의 예외."""

from app.common.errors import ConflictError, NotFoundError


class InvalidStateTransitionError(ConflictError):
    """전이 표가 거부한 전이. 표 밖의 조합은 전부 여기로 온다."""

    code = "INVALID_STATE_TRANSITION"


class ReservationNotFoundError(NotFoundError):
    """확인번호로 찾을 수 없다. **남의 예약도 이것이다** — 403을 주면
    그 확인번호가 존재한다는 사실 자체를 알려주게 된다 (스펙 2.4절)."""

    code = "RESOURCE_NOT_FOUND"
