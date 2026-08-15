"""예외 → HTTP 변환. **이 파일이 유일한 변환 지점이다.**

라우터에서 도메인 예외를 잡지 않는다. 그대로 올라오게 두고 여기서 바꾼다.
한 곳에 모아두면 "어떤 실패가 몇 번으로 나가는가"를 이 파일만 읽고 알 수 있다.
"""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.errors import (
    ConflictError,
    DomainError,
    InvalidRequestError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.common.response import ErrorResponse

logger = logging.getLogger(__name__)

# 예외의 갈래가 곧 상태 코드다. 컨텍스트가 만드는 구체 예외는 이 넷 중 하나를
# 상속하므로 여기 표를 고칠 일이 없다.
_STATUS_BY_TYPE: list[tuple[type[DomainError], int]] = [
    (InvalidRequestError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ServiceUnavailableError, 503),
]

# 예상 못 한 예외에 붙는 코드. 계약 표에 있고, 도메인 예외가 아니라 여기서만 난다.
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"


def _status_for(error: DomainError) -> int:
    for error_type, status in _STATUS_BY_TYPE:
        if isinstance(error, error_type):
            return status
    # 네 갈래 중 어디에도 속하지 않는 DomainError. 도메인이 거부한 것은 맞으므로
    # 500이 아니라 400으로 본다. 다만 이건 갈래를 안 고르고 DomainError를 직접
    # 상속했다는 뜻이라 설계 실수다. 조용히 넘기지 않는다.
    logger.warning(
        "갈래를 고르지 않은 도메인 예외다. 400으로 내보낸다. type=%s code=%s",
        type(error).__name__,
        error.code,
    )
    return 400


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        trace_id = uuid.uuid4().hex
        status = _status_for(error)
        logger.info(
            "도메인 예외 code=%s status=%s traceId=%s path=%s",
            error.code,
            status,
            trace_id,
            request.url.path,
        )
        body = ErrorResponse(code=error.code, message=error.message, trace_id=trace_id)
        return JSONResponse(status_code=status, content=body.model_dump(by_alias=True))

    @app.exception_handler(Exception)
    def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        """예상 못 한 예외. 원인은 로그에만 남기고 응답에는 추적 번호만 준다."""
        trace_id = uuid.uuid4().hex
        logger.exception("처리되지 않은 예외 traceId=%s path=%s", trace_id, request.url.path)
        body = ErrorResponse(
            code=INTERNAL_ERROR_CODE,
            message="요청을 처리하지 못했습니다",
            trace_id=trace_id,
        )
        return JSONResponse(status_code=500, content=body.model_dump(by_alias=True))
