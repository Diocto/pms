"""값 객체 불변식 (테스트 T1~T9, 스펙 1.2절·D27).

인프라 없음 — 밀리초 테스트. 불변식은 Pydantic validator가 아니라
도메인 생성자(model_post_init)에 있고, 여기서 그것을 고정한다.

T3·T4·T6은 하나라도 틀리면 재고를 잘못 깎는다. 체크아웃 당일을 점유에
넣으면 백투백 예약(앞 손님 체크아웃일 = 뒷 손님 체크인일)이 서로를 밀어낸다.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.common.errors import DomainError
from app.inventory.domain.models import Money
from app.reservation.domain.models import GuestCount, StayPeriod

REJECTED = (DomainError, ValidationError, TypeError)


def test_T1_체크아웃이_체크인보다_늦지_않으면_생성_거부():
    with pytest.raises(REJECTED):
        StayPeriod(check_in=date(2026, 9, 4), check_out=date(2026, 9, 1))
    with pytest.raises(REJECTED):
        StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 1))


def test_T2_빈_입력은_생성_거부():
    with pytest.raises(REJECTED):
        StayPeriod(check_in=None, check_out=date(2026, 9, 4))
    with pytest.raises(REJECTED):
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
    with pytest.raises(REJECTED):
        GuestCount(value=bad)


def test_T8_금액은_음수가_될_수_없다():
    with pytest.raises(REJECTED):
        Money(amount=-1)


def test_T9_금액_연산은_값이_맞고_원본이_불변이다():
    price = Money(amount=150000)
    total = price.multiply(3).multiply(2)      # 3박 × 2실
    combined = total.add(Money(amount=1000))
    assert total.amount == 900000
    assert combined.amount == 901000
    assert price.amount == 150000              # 원본 불변
    with pytest.raises(REJECTED):
        price.amount = 0                        # frozen
