"""한 애그리거트에 담기지 않는 도메인 규칙 — 가격 계산, 확인번호 생성."""

import secrets
from datetime import date

from app.inventory.domain.models import Money
from app.reservation.domain.models import StayPeriod

# 혼동 문자(0·O·1·I)를 뺀 알파벳. 전화로 불러줄 수 있어야 한다 (D7)
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_RANDOM_LENGTH = 8


def calculate_total_price(
    *, price_per_night: Money, period: StayPeriod, room_count: int
) -> Money:
    """총액 = 1박 단가 × 박수 × 객실 수. 역산하지 않고 저장한다 (스펙 1.6절)."""
    return price_per_night.multiply(period.nights()).multiply(room_count)


def generate_confirmation_code(
    *, check_in: date, hotel_id: int, room_type_id: int
) -> str:
    """`yyMMdd-H{h}R{r}-{무작위 8자}` (D7).

    **만드는 함수만 있고 읽는 함수는 없다.** 접두는 운영자가 눈으로 식별하기
    위한 것이고, 로직은 이 포맷을 절대 파싱하지 않는다 — 필요한 값은 전부
    `reservation` 컬럼에 있다. 조회는 언제나 전체 일치다.
    """
    random_part = "".join(
        secrets.choice(_CODE_ALPHABET) for _ in range(_RANDOM_LENGTH)
    )
    return f"{check_in:%y%m%d}-H{hotel_id}R{room_type_id}-{random_part}"
