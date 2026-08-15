"""F02 도메인 단위 테스트 — 스펙 §9-2 T1~T11.

전부 DB·Redis 없이 돈다. 그게 도메인 계층의 정의다 (clean-architecture.md).
시간은 주입한다 — `datetime.now()`를 부르는 순간 판정이 실행 환경의 시계에
매달린다 (coding-rules.md 금지 목록).
"""

from datetime import date, datetime, timedelta
from itertools import product

import pytest
from pydantic import ValidationError

from app.common.errors import InvalidRequestError
from app.promotion.domain.enums import ClaimEvent, ClaimStatus
from app.promotion.domain.errors import (
    DuplicateReleaseError,
    PromotionNotOpenError,
    PromotionSoldOutError,
)
from app.promotion.domain.models import (
    PromotionInventory,
    PromotionKey,
    SalesWindow,
)
from app.promotion.domain import transitions

_OPEN = datetime(2026, 9, 1, 12, 0, 0)
_CLOSE = datetime(2026, 9, 10, 12, 0, 0)


def _window() -> SalesWindow:
    return SalesWindow(open_at=_OPEN, close_at=_CLOSE)


def _inventory(*, total_quantity: int = 20, remaining: int | None = None) -> PromotionInventory:
    return PromotionInventory.create(
        key=PromotionKey(room_type_id=1, stay_date=date(2026, 9, 14)),
        window=_window(),
        price_per_night=75_000,
        total_quantity=total_quantity,
        remaining=remaining,
        now=_OPEN,
    )


# ── T1·T2 SalesWindow ────────────────────────────────────────────────

def test_T1_판매창은_마감이_시작보다_늦어야_한다():
    with pytest.raises(InvalidRequestError):
        SalesWindow(open_at=_CLOSE, close_at=_OPEN)
    with pytest.raises(InvalidRequestError):
        SalesWindow(open_at=_OPEN, close_at=_OPEN)  # 같아도 거부


def test_T2_판매창_경계는_시작_정각_포함_마감_정각_제외():
    window = _window()
    assert window.contains(_OPEN) is True                       # 시작 정각 포함
    assert window.contains(_CLOSE) is False                     # 마감 정각 제외
    assert window.contains(_OPEN - timedelta(microseconds=1)) is False
    assert window.contains(_CLOSE - timedelta(microseconds=1)) is True


# ── T3 PromotionKey ──────────────────────────────────────────────────

def test_T3_특가_식별자는_객실타입과_날짜가_전부_있어야_생성된다():
    with pytest.raises(ValidationError):
        PromotionKey(room_type_id=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        PromotionKey(stay_date=date(2026, 9, 14))  # type: ignore[call-arg]


def test_T3a_reference_직렬화는_왕복이_보존된다():
    """D15 — `reference` 형식의 주인은 F02다. 파싱은 해석기(T18f)에서 다루고,
    여기서는 형식 자체가 왕복 가능한지만 고정한다."""
    key = PromotionKey(room_type_id=3, stay_date=date(2026, 9, 16))
    assert key.to_reference() == "3:2026-09-16"
    assert PromotionKey.parse_reference("3:2026-09-16") == key


def test_T3b_reference_파싱_실패는_None이다():
    """빈 값이 곧 fail-closed의 입력이다 — 예외로 앱이 터지면 안 된다."""
    for bad in ["", "abc", "1:", ":2026-09-16", "1:2026-13-99", "1:2:3", "x:2026-09-16"]:
        assert PromotionKey.parse_reference(bad) is None


# ── T4~T7 PromotionInventory ─────────────────────────────────────────

def test_T4_총량이_1_미만이면_생성_거부():
    with pytest.raises(InvalidRequestError):
        _inventory(total_quantity=0)


def test_T4a_잔여가_총량을_넘으면_생성_거부():
    with pytest.raises(InvalidRequestError):
        _inventory(total_quantity=5, remaining=6)


def test_T5_잔여_0에서_use는_매진_예외():
    inventory = _inventory(total_quantity=1, remaining=0)
    with pytest.raises(PromotionSoldOutError):
        inventory.use(now=_OPEN)


def test_T6_판매창_밖에서_use는_미오픈_예외():
    inventory = _inventory()
    with pytest.raises(PromotionNotOpenError):
        inventory.use(now=_OPEN - timedelta(seconds=1))   # 오픈 전
    with pytest.raises(PromotionNotOpenError):
        inventory.use(now=_CLOSE)                          # 마감 정각부터 거부


def test_T6a_판매창_안이면_use가_잔여를_1_줄인다():
    inventory = _inventory(total_quantity=20)
    inventory.use(now=_OPEN)
    assert inventory.remaining == 19


def test_T7_잔여가_총량과_같으면_release는_이중_반납_예외():
    inventory = _inventory(total_quantity=20)   # remaining == total_quantity
    with pytest.raises(DuplicateReleaseError):
        inventory.release()


def test_T7a_release는_잔여를_1_되돌린다():
    inventory = _inventory(total_quantity=20, remaining=19)
    inventory.release()
    assert inventory.remaining == 20


# ── T8·T9·T11 전이 표 ────────────────────────────────────────────────

def test_T8_USED에서_RELEASE는_RELEASED로_간다():
    resolution = transitions.resolve(ClaimStatus.USED, ClaimEvent.RELEASE)
    assert resolution.is_idempotent is False
    assert resolution.next_status is ClaimStatus.RELEASED
    assert resolution.restores_inventory is True


def test_T9_전이_조합_전수_검증():
    """(상태 × 이벤트) 전 조합이 허용·멱등·거부 중 정확히 하나로 판정된다.

    지금은 이벤트가 하나라 거부 조합이 0개다 — 그래도 전수 루프를 남겨둔다.
    이벤트가 추가되는 순간 표에 없는 조합이 자동으로 거부로 판정되는지를
    이 테스트가 잡는다. 표 밖 전이는 반드시 예외여야 한다.
    """
    for status, event in product(ClaimStatus, ClaimEvent):
        in_allowed = (status, event) in transitions.ALLOWED
        in_idempotent = (status, event) in transitions.IDEMPOTENT
        assert not (in_allowed and in_idempotent), f"{status}·{event}가 두 표에 다 있다"
        if in_allowed or in_idempotent:
            transitions.resolve(status, event)  # 예외 없이 판정돼야 한다
        else:
            with pytest.raises(InvalidRequestError):
                transitions.resolve(status, event)


def test_T11_RELEASED에서_RELEASE는_멱등이고_재고를_되돌리지_않는다():
    resolution = transitions.resolve(ClaimStatus.RELEASED, ClaimEvent.RELEASE)
    assert resolution.is_idempotent is True
    assert resolution.next_status is None
    assert resolution.restores_inventory is False


# ── T10 PromotionClaim ───────────────────────────────────────────────

def test_T10_사용권은_예약_없이_생성되지_않는다():
    """불변식 5 — 예약이 먼저 만들어진 뒤에야 사용권이 생긴다 (C4)."""
    from app.promotion.domain.models import PromotionClaim

    with pytest.raises(ValidationError):
        PromotionClaim.issue(  # type: ignore[call-arg]
            key=PromotionKey(room_type_id=1, stay_date=date(2026, 9, 14)),
            user_id="42",
            idempotency_key="idem-1",
            applied_price=75_000,
            used_at=_OPEN,
        )


def test_T10a_사용권은_태어날_때_USED이고_반납_시각이_비어_있다():
    from app.promotion.domain.models import PromotionClaim

    claim = PromotionClaim.issue(
        key=PromotionKey(room_type_id=1, stay_date=date(2026, 9, 14)),
        reservation_id=100,
        user_id="42",
        idempotency_key="idem-1",
        applied_price=75_000,
        used_at=_OPEN,
    )
    assert claim.status == ClaimStatus.USED.value
    assert claim.released_at is None
    assert claim.reservation_id == 100
