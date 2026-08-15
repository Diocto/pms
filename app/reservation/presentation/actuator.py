"""운영 확인 엔드포인트 — `GET /api/internal/config` (D26).

F04의 락 On/Off 대조가 실행 전에 여기를 읽는다. 값은 컨테이너의 **리스트
프로바이더**로 모은 컨텍스트별 기여(`RuntimeContributor`)를 병합한 것이고,
그 기여는 락 구현이 실제로 쓰는 같은 프로바이더에서 나온다.
"""

import os

from fastapi import APIRouter, Request

from app.common.runtime_report import merge_reports
from app.reservation.presentation.schemas import RuntimeConfigResponse

router = APIRouter()


@router.get("/api/internal/config", response_model=RuntimeConfigResponse)
def get_runtime_config(request: Request) -> RuntimeConfigResponse:
    container = request.app.state.container
    merged = merge_reports(
        contributor.report() for contributor in container.runtime_contributors()
    )
    return RuntimeConfigResponse(
        load_test=merged.load_test,
        implementations=merged.implementations,
        counters=merged.counters,
        process_id=os.getpid(),
    )
