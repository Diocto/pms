"""inventory 리포지토리 계약. 구현은 `infrastructure/persistence.py`에 있다.

구현은 **호출부의 세션을 받아서만 쓴다.** 스스로 세션을 열면 트랜잭션이
갈라진다 (coding-rules.md). 날짜 정렬도 구현의 몫이다 — 호출부는 정렬을
신경 쓸 기회조차 없어야 락 순서와 행 접근 순서가 같은 목록에서 나온다 (D10).
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from sqlalchemy.orm import Session


class InventoryRepository(Protocol):
    def deduct(
        self,
        session: Session,
        *,
        room_type_id: int,
        stay_dates: Sequence[date],
        room_count: int,
        now: datetime,
    ) -> None:
        """날짜 오름차순으로 행마다 조건부 UPDATE. 어느 하루라도 부족하면
        `InsufficientInventoryError` — 호출부의 트랜잭션 롤백으로 앞 날짜
        차감분도 함께 되돌아간다."""

    def restore(
        self,
        session: Session,
        *,
        room_type_id: int,
        stay_dates: Sequence[date],
        room_count: int,
        now: datetime,
    ) -> None:
        """차감의 역. 갱신 행 수가 날짜 수와 다르면
        `InventoryRestoreMismatchError` — 이중 복원 감지다."""
