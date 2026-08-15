"""한 애그리거트에 담기지 않는 도메인 규칙.

가격 계산은 여기 없다 — 단가·기간·객실 수는 전부 애그리거트 자신의 데이터라
`Reservation.create()` 안에 있다 (2회차 리뷰). 할인 해석이 붙는 가격 결정은
3회차의 `DiscountResolver` 포트(D22) 몫이다.
"""

import secrets
from datetime import date

from app.inventory.domain.models import RoomType

# 혼동 문자(0·O·1·I)를 뺀 알파벳. 전화로 불러줄 수 있어야 한다 (D7)
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_RANDOM_LENGTH = 8


def generate_confirmation_code(*, check_in: date, room_type: RoomType) -> str:
    """`yyMMdd-H{h}R{r}-{무작위 8자}` (D7).

    **만드는 함수만 있고 읽는 함수는 없다.** 접두는 운영자가 눈으로 식별하기
    위한 것이고, 로직은 이 포맷을 절대 파싱하지 않는다 — 필요한 값은 전부
    `reservation` 컬럼에 있다. 조회는 언제나 전체 일치다.
    """
    random_part = "".join(
        secrets.choice(_CODE_ALPHABET) for _ in range(_RANDOM_LENGTH)
    )
    return f"{check_in:%y%m%d}-H{room_type.hotel_id}R{room_type.id}-{random_part}"
