"""공용 실행 상태 노출 계약의 F03 기여자 (D15, F01 D26).

라우터가 아니다 — `app/common/runtime_report.py`의 `RuntimeContributor`
구현이고, F01 소유 엔드포인트(`GET /api/internal/config`)가 모아 내보낸다.
"""

from app.common.config import Settings
from app.common.runtime_report import RuntimeReport
from app.inventory.query.application.ports import AvailabilityCachePort


class SearchRuntimeContributor:
    """캐시 스위치의 "의도한 값"과 "실제로 들어간 구현"을 함께 보고한다.

    구현 이름은 손으로 적지 않고 주입된 실물에서 뽑는다 — 문자열 상수로
    적으면 그 상수가 또 하나의 "따로 선언된 설정"이 되어 어긋날 자리가 된다.
    누적 카운터는 싣지 않는다 (D15) — 캐시 생사는 모든 200 응답의
    `source` 필드에 표본 단위로 이미 실려 나간다.
    """

    def __init__(self, settings: Settings, cache: AvailabilityCachePort) -> None:
        self._settings = settings
        self._cache = cache

    def report(self) -> RuntimeReport:
        return RuntimeReport(
            load_test={
                "PMS_SEARCH_CACHE_ENABLED": self._settings.search_cache_enabled,
                "PMS_SEARCH_CACHE_TTL_SECONDS": (
                    self._settings.search_cache_ttl_seconds
                ),
            },
            implementations={"searchCache": type(self._cache).__name__},
        )
