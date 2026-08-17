"""운영 확인 엔드포인트 — `GET /api/internal/config` (D26).

부하테스트의 락 On/Off 대조가 실행 전에 여기를 읽는다. 값은 컨테이너의 **리스트
프로바이더**로 모은 컨텍스트별 기여(`RuntimeContributor`)를 병합한 것이고,
그 기여는 락 구현이 실제로 쓰는 같은 프로바이더에서 나온다.
"""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.common.runtime_report import merge_reports
from app.reservation.presentation.schemas import RuntimeConfigResponse

router = APIRouter(tags=["internal"])


def runtime_contributors(request: Request) -> list:
    """컨텍스트별 실행 상태 기여자 목록 (D26). 컨테이너 접근은 여기 한 곳이다."""
    return request.app.state.container.runtime_contributors()


@router.get(
    "/api/internal/config",
    response_model=RuntimeConfigResponse,
    summary="실행 설정 확인 (부하테스트용)",
)
def get_runtime_config(
    contributors: Annotated[list, Depends(runtime_contributors)],
) -> RuntimeConfigResponse:
    """락·캐시 스위치 등 실행 시점 설정과 실제 주입된 구현 이름을 돌려준다.

    부하테스트의 락 On/Off 대조가 실행 전에 이 값을 읽어 확인한다 (D26).
    """
    merged = merge_reports(contributor.report() for contributor in contributors)
    return RuntimeConfigResponse(
        load_test=merged.load_test,
        implementations=merged.implementations,
        counters=merged.counters,
        process_id=os.getpid(),
    )
