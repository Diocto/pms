"""검색 유스케이스의 입출력 그릇과 VO (스펙 4절).

계층을 넘는 그릇은 전부 frozen Pydantic이다 — 캐시 키를 검색 조건에서
만들므로, 조건이 도중에 바뀌면 키와 값이 어긋난다.
"""

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.common.errors import InvalidRequestError

# 상한을 두는 이유: 기간이 길수록 집계 쿼리가 만지는 행 수가 늘어나는데,
# 상한이 없으면 요청 하나가 쿼리 비용을 마음대로 키울 수 있다
MAX_NIGHTS = 30


class StayRange(BaseModel):
    """투숙 기간. 체크아웃 당일은 점유하지 않는다.

    F01의 StayPeriod와 규칙이 같지만 그건 reservation 구역 소유라 참조하지
    않는다 (00 D6). "오늘"에 걸리는 규칙만 `ensure_not_past`로 분리한다 —
    오늘이 언제인지는 이 객체가 알 수 없고, 시계를 주입받은 쪽이 준다 (D14).
    """

    model_config = ConfigDict(frozen=True)

    check_in: date
    check_out: date

    def model_post_init(self, _context: Any) -> None:
        # 불변식은 validator가 아니라 생성 시점의 도메인 검증이다 (D27)
        if self.check_out <= self.check_in:
            raise InvalidRequestError("체크아웃은 체크인보다 뒤여야 합니다")
        if self.nights() > MAX_NIGHTS:
            raise InvalidRequestError(f"투숙은 {MAX_NIGHTS}박을 넘을 수 없습니다")

    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    def occupied_dates(self) -> list[date]:
        """점유하는 날짜들 — 체크아웃 당일은 없다.

        이 목록의 길이가 곧 `nights()`이고, 집계 쿼리의
        `HAVING COUNT(*) = :nights` 판정이 이 정의 위에 서 있다.
        """
        return [
            self.check_in + timedelta(days=offset) for offset in range(self.nights())
        ]

    def ensure_not_past(self, today: date) -> None:
        if self.check_in < today:
            raise InvalidRequestError("체크인은 오늘보다 앞설 수 없습니다")
