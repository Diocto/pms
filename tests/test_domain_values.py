"""값 객체 불변식 (테스트 T1~T9, 스펙 1.2절·D27).

인프라 없음 — 밀리초 테스트. 불변식은 Pydantic validator가 아니라
도메인 생성자(model_post_init)에 있고, 여기서 그것을 고정한다.

T3·T4·T6은 하나라도 틀리면 재고를 잘못 깎는다. 체크아웃 당일을 점유에
넣으면 백투백 예약(앞 손님 체크아웃일 = 뒷 손님 체크인일)이 서로를 밀어낸다.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.common.errors import InvalidRequestError
from app.inventory.domain.models import Money
from app.reservation.domain.models import GuestCount, StayPeriod

# 타입 오류(빈 입력·frozen 위반)는 Pydantic이 잡는다
TYPE_REJECTED = (ValidationError, TypeError)


def test_T1_체크아웃이_체크인보다_늦지_않으면_생성_거부():
    # 불변식 위반은 도메인 예외여야 한다. 넓은 튜플로 받으면 불변식을
    # validator로 옮겨도(D27 위반) 초록이다 (리뷰 지적)
    with pytest.raises(InvalidRequestError):
        StayPeriod(check_in=date(2026, 9, 4), check_out=date(2026, 9, 1))
    with pytest.raises(InvalidRequestError):
        StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 1))


def test_T1b_투숙_기간에_박수_상한이_없다():
    # D29 뒤집음 (관리자, 8/16). 예약 가능한 기간은 코드 상한이 아니라
    # 재고를 열어둔 날짜 범위가 정한다 — 재고 행이 없는 날짜는 차감이 0행이라 409
    period = StayPeriod(check_in=date(2026, 8, 16), check_out=date(2030, 1, 1))
    assert period.nights() == 1234


def test_T2_빈_입력은_생성_거부():
    with pytest.raises(TYPE_REJECTED):
        StayPeriod(check_in=None, check_out=date(2026, 9, 4))
    with pytest.raises(TYPE_REJECTED):
        StayPeriod(check_in=date(2026, 9, 1), check_out=None)


def test_T3_점유_날짜는_체크아웃_당일을_포함하지_않는다():
    period = StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    assert period.occupied_dates() == [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
    ]


def test_T4_1박이면_점유_날짜는_하나다():
    period = StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 2))
    assert period.occupied_dates() == [date(2026, 9, 1)]


def test_T5_박수_계산():
    period = StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    assert period.nights() == 3


def test_T6_백투백_예약은_점유가_겹치지_않는다():
    first = StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 3))
    second = StayPeriod(check_in=date(2026, 9, 3), check_out=date(2026, 9, 5))
    assert set(first.occupied_dates()) & set(second.occupied_dates()) == set()


@pytest.mark.parametrize("bad", [0, -1])
def test_T7_인원은_1_이상이다(bad):
    with pytest.raises(InvalidRequestError):
        GuestCount(value=bad)


def test_T8_금액은_음수가_될_수_없다():
    with pytest.raises(InvalidRequestError):
        Money(amount=-1)


def test_T9_금액_연산은_값이_맞고_원본이_불변이다():
    price = Money(amount=150000)
    total = price.multiply(3).multiply(2)      # 3박 × 2실
    combined = total.add(Money(amount=1000))
    assert total.amount == 900000
    assert combined.amount == 901000
    assert price.amount == 150000              # 원본 불변
    with pytest.raises(TYPE_REJECTED):
        price.amount = 0                        # frozen
