"""검색 유스케이스의 입출력 그릇과 VO (스펙 4절).

계층을 넘는 그릇은 전부 frozen Pydantic이다 — 캐시 키를 검색 조건에서
만들므로, 조건이 도중에 바뀌면 키와 값이 어긋난다.
"""

from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.common.errors import InvalidRequestError, NotFoundError

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


class SearchAvailableRoomsQuery(BaseModel):
    """검색 조건 — 캐시 키가 이 값들로만 만들어진다.

    조건 하나가 빠지면 곧바로 다른 조건의 결과를 돌려주는 버그가 되므로
    한 객체로 묶고, `fresh`만 캐시 우회 지시라 키에 넣지 않는다.
    """

    model_config = ConfigDict(frozen=True)

    hotel_id: int
    stay: StayRange
    guest_count: int
    room_count: int
    fresh: bool = False

    def cache_key(self) -> str:
        """캐시 키 (스펙 7절). `fresh`만 뺀다 — 캐시를 읽을지 정하는 값이지
        결과를 바꾸는 값이 아니다. 나머지 조건은 하나도 빼지 않는다 (I6)."""
        return (
            f"avail:{self.hotel_id}"
            f":{self.stay.check_in.isoformat()}:{self.stay.check_out.isoformat()}"
            f":{self.guest_count}:{self.room_count}"
        )


class EmptyReason(str, Enum):
    """빈 결과의 이유. 문자열이 곧 계약이다 — F04·F05가 생 문자열로 비교하므로
    대문자 고정이고 name과 value가 같다. 값을 바꾸면 상대 검증이 조용히 죽는다."""

    SOLD_OUT = "SOLD_OUT"
    NOT_YET_OPEN = "NOT_YET_OPEN"
    NO_FITTING_ROOM_TYPE = "NO_FITTING_ROOM_TYPE"


class AvailabilityDiagnosis(BaseModel):
    """진단 쿼리 한 발의 결과. 집계가 비었을 때만 만들어진다 (스펙 8절)."""

    model_config = ConfigDict(frozen=True)

    room_type_count: int
    fitting_room_type_count: int
    sales_open_until: date | None

    def empty_reason(self, stay: StayRange) -> EmptyReason:
        """판정 순서가 계약이다 — 위에서부터 먼저 걸리는 것을 쓴다.

        `sales_open_until`은 재고 행이 존재하는 마지막 날짜이고, 체크아웃
        당일은 점유하지 않으므로 마지막 투숙 밤과 비교한다 (D9).
        """
        if self.room_type_count == 0:
            raise NotFoundError("호텔을 찾을 수 없습니다")
        if self.fitting_room_type_count == 0:
            return EmptyReason.NO_FITTING_ROOM_TYPE
        last_night = stay.check_out - timedelta(days=1)
        if self.sales_open_until is None or self.sales_open_until < last_night:
            return EmptyReason.NOT_YET_OPEN
        return EmptyReason.SOLD_OUT


class AvailableRoomTypeView(BaseModel):
    """객실타입 한 줄. `min_remaining`이 "이 기간을 통째로 몇 개까지 잡을 수
    있는가"다 — 기간 중 가장 빡빡한 날의 잔여."""

    model_config = ConfigDict(frozen=True)

    room_type_id: int
    room_type_name: str
    capacity: int
    min_remaining: int
    price_per_night: int
    total_price: int


class Source(str, Enum):
    """이 응답이 어디서 왔는가. F04가 생 문자열로 비교하는 계약이다 —
    표본이 말라도 임계값 검사는 조용히 통과하므로, 값이 어긋나면 안 잡힌다."""

    CACHE = "CACHE"
    DB = "DB"


class AvailableRoomsResult(BaseModel):
    """검색 결과 전체. 낡음을 숨기지 않는다 — 언제 찍힌 스냅샷인지(`searched_at`),
    어디서 왔는지(`source`), 얼마나 낡을 수 있는지(`stale_tolerance_seconds`)를
    함께 실어 보낸다 (G2)."""

    model_config = ConfigDict(frozen=True)

    searched_at: datetime
    source: Source
    stale_tolerance_seconds: int
    items: list[AvailableRoomTypeView]
    empty_reason: EmptyReason | None = None
    sales_open_until: date | None = None


class HotelRoomTypeView(BaseModel):
    """호텔 목록의 객실타입 한 줄 — 정적 마스터 정보만. 잔여는 검색이 답한다."""

    model_config = ConfigDict(frozen=True)

    room_type_id: int
    name: str
    capacity: int
    total_quantity: int
    base_price: int


class HotelView(BaseModel):
    """호텔 한 곳과 그 객실타입 매핑 (관리자 지시 2026-08-16, F05 검색 화면용)."""

    model_config = ConfigDict(frozen=True)

    hotel_id: int
    name: str
    address: str
    room_types: list[HotelRoomTypeView]
