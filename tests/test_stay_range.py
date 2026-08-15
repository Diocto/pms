"""StayRange VO의 날짜 규칙 (스펙 4절 입력 규칙, TDD 1~3, T3).

전부 고정 날짜로 검증한다. "오늘"은 인자로 주입한다 — 테스트가 실행
시점에 따라 흔들리면 경계 검증이 아니다 (D14).
"""

from datetime import date

import pytest

from app.common.errors import InvalidRequestError
from app.inventory.query.application.commands import StayRange


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


# --- TDD 3. 31박 이상과 과거 체크인을 거부한다 ---


def test_삼십일박은_상한_안이다() -> None:
    stay = StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 10, 1))
    assert stay.nights() == 30


def test_삼십일박을_넘으면_거부한다() -> None:
    with pytest.raises(InvalidRequestError):
        StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 10, 2))


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
