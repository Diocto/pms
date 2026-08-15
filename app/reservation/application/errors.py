"""application 계층의 예외 — 락·멱등 흐름에서 나는 것들."""

from app.common.errors import ConflictError, ServiceUnavailableError


class LockAcquisitionError(ServiceUnavailableError):
    """대기 상한 안에 락을 전부 잡지 못했다. 요청 잘못이 아니라 **혼잡**이다 —
    잠시 뒤 그대로 재시도하면 된다 (503)."""

    code = "LOCK_ACQUISITION_FAILED"


class RequestInProgressError(ConflictError):
    """같은 멱등 키의 요청이 처리 중이다. 대기시키지 않는다 — 대기는 커넥션을
    잡아둬 부하 상황에서 더 나쁘다 (스펙 3.4절)."""

    code = "REQUEST_IN_PROGRESS"
