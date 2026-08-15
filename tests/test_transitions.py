"""전이 표 36칸 전수 (테스트 T10~T15, 스펙 1.4절).

허용 7 + 멱등 6 + 거부 23 = 36. **표를 고치면 이 테스트가 먼저 깨진다** —
그것이 목적이다. 이 파일의 리터럴은 스펙 1.4절 표를 그대로 옮긴 것이라,
코드의 표가 스펙과 어긋나면 여기서 드러난다 (T15).
"""

import pytest

from app.reservation.domain.enums import ReservationEvent as E
from app.reservation.domain.enums import ReservationStatus as S
from app.reservation.domain.errors import InvalidStateTransitionError
from app.reservation.domain.transitions import ALLOWED, IDEMPOTENT, resolve

# ── 스펙 1.4절 표의 리터럴 사본. 코드에서 import하지 않는다 ──
# (코드의 표를 읽어서 검증하면 표가 잘못돼도 같이 잘못된다)

SPEC_ALLOWED = {
    # (현재, 이벤트) -> (다음, 재고 복원 여부)
    (S.PENDING, E.CONFIRM): (S.CONFIRMED, False),
    (S.PENDING, E.PAYMENT_FAILED): (S.CANCELLED, True),
    (S.PENDING, E.CANCEL): (S.CANCELLED, True),
    (S.PENDING, E.EXPIRE): (S.EXPIRED, True),
    (S.CONFIRMED, E.CANCEL): (S.CANCELLED, True),
    (S.CONFIRMED, E.CHECK_IN): (S.CHECKED_IN, False),
    (S.CHECKED_IN, E.CHECK_OUT): (S.CHECKED_OUT, False),
}

SPEC_IDEMPOTENT = {
    (S.CONFIRMED, E.CONFIRM),
    (S.CHECKED_IN, E.CHECK_IN),
    (S.CHECKED_OUT, E.CHECK_OUT),
    (S.CANCELLED, E.PAYMENT_FAILED),
    (S.CANCELLED, E.CANCEL),
    (S.EXPIRED, E.EXPIRE),
}

SPEC_REJECTED = [
    (status, event)
    for status in S
    for event in E
    if (status, event) not in SPEC_ALLOWED and (status, event) not in SPEC_IDEMPOTENT
]


def test_T10_종료_상태는_정확히_셋이다():
    assert [s for s in S if s.is_terminal] == [S.CHECKED_OUT, S.CANCELLED, S.EXPIRED]


@pytest.mark.parametrize(("pair", "expected"), SPEC_ALLOWED.items())
def test_T11_허용_7칸은_지정된_다음_상태로_간다(pair, expected):
    status, event = pair
    next_status, restores = expected
    resolution = resolve(status, event)
    assert resolution.is_idempotent is False
    assert resolution.next_status == next_status
    assert resolution.restores_inventory is restores


@pytest.mark.parametrize("pair", sorted(SPEC_IDEMPOTENT, key=str))
def test_T12_멱등_6칸은_상태를_바꾸지_않고_성공한다(pair):
    status, event = pair
    resolution = resolve(status, event)
    assert resolution.is_idempotent is True
    assert resolution.next_status is None
    # 멱등 전이가 재고를 건드리면 이중 복원이다 (1.4절)
    assert resolution.restores_inventory is False


@pytest.mark.parametrize("pair", SPEC_REJECTED)
def test_T13_거부_23칸은_예외다(pair):
    status, event = pair
    with pytest.raises(InvalidStateTransitionError):
        resolve(status, event)


def test_T13a_거부_칸은_정확히_23개다():
    # 36 - 7 - 13... 이 아니라 36 - 7 - 6 = 23. 파라미터 계산 자체를 검증한다
    assert len(SPEC_REJECTED) == 23


def test_T14_표의_등록_개수_자체를_고정한다():
    """T11~T13은 표를 *읽어서* 검증하므로 표가 잘못돼도 같이 잘못될 수 있다.
    개수를 상수로 박아 표 자체의 변경을 잡는다. 전이를 추가하면 여기가 먼저 깨진다."""
    assert len(ALLOWED) == 7
    assert len(IDEMPOTENT) == 6


def test_T15_코드의_표와_스펙_사본이_한_칸도_다르지_않다():
    assert {
        pair: (resolution.next_status, resolution.restores_inventory)
        for pair, resolution in ALLOWED.items()
    } == SPEC_ALLOWED
    assert IDEMPOTENT == frozenset(SPEC_IDEMPOTENT)


def test_거부_이유_문구는_현재_상태를_말한다():
    # EXPIRED + CANCEL 거부 시 "이미 취소됨"이 아니라 "만료됨"이라고 답해야
    # 한다 (1.4절 읽는 법). 메시지에 현재 상태가 실려야 그 응답이 가능하다
    with pytest.raises(InvalidStateTransitionError) as excinfo:
        resolve(S.EXPIRED, E.CANCEL)
    assert "EXPIRED" in str(excinfo.value)
