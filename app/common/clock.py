"""시계.

**도메인 코드에서 `datetime.now()`를 직접 부르지 않는다.** 시각이 코드에 박히면
"체크아웃일이 지난 예약은 체크인할 수 없다" 같은 규칙을 테스트할 때 시스템 시각을
조작해야 한다. 시계를 주입받으면 그 규칙을 밀리초 단위 단위 테스트로 검증할 수 있다.

**기준 시간대는 `Asia/Seoul`로 고정한다.** 숙박은 "며칠에 묵는가"가 곧 재고 행의
식별자다. 서버가 UTC로 날짜를 계산하면 한국 시간 오전 9시 이전 요청이 전날 재고를
차감한다.
"""

from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    """운영에서 쓰는 시계."""

    def now(self) -> datetime:
        return datetime.now(KST)

    def today(self) -> date:
        return self.now().date()


class FixedClock:
    """테스트에서 특정 시점을 고정한다."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=KST)
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def today(self) -> date:
        return self._instant.date()
