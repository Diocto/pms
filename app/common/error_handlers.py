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
)
from app.common.response import ErrorResponse

logger = logging.getLogger(__name__)

# 예외의 갈래가 곧 상태 코드다. 컨텍스트가 만드는 구체 예외는 이 셋 중 하나를
# 상속하므로 여기 표를 고칠 일이 없다.
_STATUS_BY_TYPE: list[tuple[type[DomainError], int]] = [
    (InvalidRequestError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
]


def _status_for(error: DomainError) -> int:
    for error_type, status in _STATUS_BY_TYPE:
        if isinstance(error, error_type):
            return status
    # 세 갈래 중 어디에도 속하지 않는 DomainError. 도메인이 거부한 것은 맞으므로
    # 500이 아니라 400으로 본다.
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
            code="INTERNAL_ERROR",
            message="요청을 처리하지 못했습니다",
            trace_id=trace_id,
        )
        return JSONResponse(status_code=500, content=body.model_dump(by_alias=True))
