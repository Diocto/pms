"""inventory 컨텍스트의 예외."""

from app.common.errors import ConflictError


class InsufficientInventoryError(ConflictError):
    """요청한 날짜의 잔여 객실이 부족하다. 조건부 UPDATE의 rowcount 0이 이것이다."""

    code = "INSUFFICIENT_INVENTORY"


class InventoryRestoreMismatchError(Exception):
    """복원 갱신 행 수가 점유 날짜 수와 다르다 — 이중 복원 방지 논리가 어딘가에서
    깨졌다는 뜻이다 (스펙 3.2절).

    도메인이 거부한 요청이 아니라 **시스템 불변식의 파손**이므로 `DomainError`가
    아니다. 500으로 올라가고, 트랜잭션은 롤백되며, 조용히 넘기지 않는다.
    """
