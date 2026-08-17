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


# ── 저장소가 UK 위반을 번역해 던지는 신호 (D7·D9) ─────────────────────
# HTTP로 나가는 에러가 아니라 유스케이스의 분기 신호다. 문자열 매칭으로
# 예외를 가르는 코드는 금지라서(관리자 지시), 드라이버 메시지 해석은
# 저장소 안 한 곳에만 있고 바깥은 이 타입으로만 분기한다.


class DuplicateConfirmationCodeError(Exception):
    """확인번호 UNIQUE 충돌 — 무작위 8자가 겹쳤다. 새 코드로 재생성한다 (D7)."""


class DuplicateIdempotencyKeyError(Exception):
    """멱등 키 UNIQUE 충돌 — Redis가 뚫려 같은 키가 두 번 들어왔다.
    DB UK가 정답이므로 기존 예약을 재생 응답한다 (D9)."""
