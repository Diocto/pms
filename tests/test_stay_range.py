"""StayRange VO의 날짜 규칙 (스펙 4절 입력 규칙, TDD 1~3, T3).

전부 고정 날짜로 검증한다. "오늘"은 인자로 주입한다 — 테스트가 실행
시점에 따라 흔들리면 경계 검증이 아니다 (D14).
"""

from datetime import date

import pytest

from app.common.errors import InvalidRequestError
from app.inventory.query.application.commands import (
    AvailabilityDiagnosis,
    EmptyReason,
    StayRange,
)


# --- TDD 1. 체크아웃이 체크인보다 앞서면 거부한다 ---


def test_체크아웃이_체크인보다_앞서면_거부한다() -> None:
    with pytest.raises(InvalidRequestError):
        StayRange(check_in=date(2026, 9, 2), check_out=date(2026, 9, 1))


def test_체크인과_체크아웃이_같아도_거부한다() -> None:
    # 0박. "1박 이상"의 하한 경계다
    with pytest.raises(InvalidRequestError):
        StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 1))


# --- TDD 2. 점유 날짜에 체크아웃 당일이 없다 ---


def test_점유_날짜에_체크아웃_당일이_없다() -> None:
    stay = StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    assert stay.occupied_dates() == [
        date(2026, 9, 1),
        date(2026, 9, 2),
        date(2026, 9, 3),
    ]


def test_일박이면_점유_날짜는_체크인_하루다() -> None:
    stay = StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 2))
    assert stay.occupied_dates() == [date(2026, 9, 1)]
    assert stay.nights() == 1


def test_박수는_점유_날짜_수와_같다() -> None:
    stay = StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    assert stay.nights() == 3
    assert stay.nights() == len(stay.occupied_dates())


# --- TDD 3. 박수 상한은 없다. 과거 체크인은 거부한다 ---


def test_박수_상한이_없다() -> None:
    """예약(F01 D29, 관리자 8/16 "제한 없이")과 같은 규칙을 검색도 따른다.

    상한이 되살아나면 여기가 빨강이 된다 — 40박 예약은 되는데 40박 검색은
    400이던 어긋남을 다시 만들지 않기 위한 자리다.
    """
    for check_out, expected_nights in (
        (date(2026, 10, 2), 31),  # 옛 상한(30박) 바로 위
        (date(2027, 9, 1), 365),
    ):
        stay = StayRange(check_in=date(2026, 9, 1), check_out=check_out)
        assert stay.nights() == expected_nights


def test_재고_범위를_넘는_기간은_상한이_아니라_판정이_거른다() -> None:
    """긴 기간을 막던 것이 사라져도 결과가 이상해지지 않는 이유.

    재고 행이 없는 날짜가 끼면 그 객실타입은 집계에서 빠지고(D9 fail-closed),
    빈 결과의 이유는 `NOT_YET_OPEN`으로 나간다 — 400이 아니라 200이다.
    실제 판정은 `test_availability_diagnosis.py`가 확인한다.
    """
    stay = StayRange(check_in=date(2026, 9, 1), check_out=date(2027, 9, 1))
    diagnosis = AvailabilityDiagnosis(
        room_type_count=3,
        fitting_room_type_count=3,
        sales_open_until=date(2026, 10, 29),  # 시드 마지막 날짜
    )
    assert diagnosis.empty_reason(stay) is EmptyReason.NOT_YET_OPEN


def test_과거_체크인을_거부한다() -> None:
    stay = StayRange(check_in=date(2026, 8, 15), check_out=date(2026, 8, 20))
    with pytest.raises(InvalidRequestError):
        stay.ensure_not_past(today=date(2026, 8, 16))


def test_오늘_체크인은_과거가_아니다() -> None:
    stay = StayRange(check_in=date(2026, 8, 16), check_out=date(2026, 8, 20))
    stay.ensure_not_past(today=date(2026, 8, 16))  # 예외 없음


def test_규칙_위반은_400으로_이어지는_공통_예외다() -> None:
    # 라우터가 별도 매핑 없이 공통 처리기로 400 INVALID_REQUEST를 내는 근거
    with pytest.raises(InvalidRequestError) as exc:
        StayRange(check_in=date(2026, 9, 2), check_out=date(2026, 9, 1))
    assert exc.value.code == "INVALID_REQUEST"
