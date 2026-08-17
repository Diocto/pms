"""유스케이스가 아는 바깥 세계의 전부 — 포트 (스펙 3.6절, D10).

구현은 `infrastructure/`에 있고 컨테이너가 조립한다. 유스케이스는 어느
구현이 왔는지 모른다. 락은 켠 것과 끈 것(NoOp)이 같은 포트 뒤에 있어
`PMS_LOCK_ENABLED` 하나로 갈린다 — 끌 수 없는 층은 살아 있는지 확인할
방법이 없다.

한때 선착순 특가(폐기, ADR-0058)를 위한 확장 훅 4종이 여기 있었다.
구현이 0개인 채 계약만 남아 읽기를 방해해서 제거했다 (ADR-0065).
설계 기록은 `docs/spec/F02-선착순-프로모션.md`에 남아 있다.
"""

from collections.abc import Iterable
from contextlib import AbstractContextManager
from datetime import date
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


# ── 분산락 (3.3절, D10) ─────────────────────────────────────────────

@runtime_checkable
class LockPort(Protocol):
    def acquire_all(
        self, keys: list[str], *, wait_s: float, ttl_s: int
    ) -> AbstractContextManager[None]:
        """받은 키를 **정렬해서** 전부 잠근다. 호출부는 순서를 신경 쓸 기회조차
        없다 — 넘기는 것은 집합이고 순서는 구현의 몫이다.
        하나라도 실패하면 `LockAcquisitionError` (503)."""


class LockPolicy(BaseModel):
    """락을 "어떻게 쓰는가"를 한 덩어리로 묶는다 (ADR-0064).

    `wait_s`·`ttl_s`가 락과 떨어져 원시값으로 돌아다니면 밀리초를 초에 넣는
    실수를 잡을 자리가 없다 — 3회차 리뷰가 실제로 지적한 그 실수다. 지금은
    조립의 변환 지점 하나가 막고 있는데, 이 묶음이 그 방어를 타입으로 올린다.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    lock: LockPort
    wait_s: float
    ttl_s: int

    def hold_inventory(
        self, *, room_type_id: int, stay_dates: Iterable[date]
    ) -> AbstractContextManager[None]:
        """재고 행들에 대한 분산락을 with 한 문장으로 잡는다.

        키 규약(`lock:inventory:{객실타입}:{날짜}`)과 대기·수명 값이 전부
        여기 있으므로, 유스케이스에는 "어느 재고를 잠그는가"만 남는다.
        해제는 with를 빠져나올 때 자동이다 — 명시적 해제 코드는 없다.
        """
        keys = [
            f"lock:inventory:{room_type_id}:{stay_date}" for stay_date in stay_dates
        ]
        return self.lock.acquire_all(keys, wait_s=self.wait_s, ttl_s=self.ttl_s)


# ── 멱등성 (3.4절, D9·D18) ──────────────────────────────────────────

class IdempotencyClaim(BaseModel):
    """선점 시도의 결과 4상태.

    - `acquired` — 최초 요청. 처리 후 `store()` 또는 `store_failure()`를 부른다
    - `processing` — 같은 키가 처리 중. 409 `REQUEST_IN_PROGRESS`
    - `done` — 성공으로 처리됨. `confirmation_code`로 조회해 200 + 같은 본문
    - `failed` — 실패로 완료됨(재고 부족 등). `failure_code`의 **같은 409**를
      다시 돌려준다 — 같은 키 재요청은 같은 결과를 받는다 (D18·D30)
    """

    model_config = ConfigDict(frozen=True)

    outcome: Literal["acquired", "processing", "done", "failed"]
    confirmation_code: str | None = None
    failure_code: str | None = None


class IdempotencyPort(Protocol):
    def claim(self, *, user_id: str, key: str, ttl_seconds: int) -> IdempotencyClaim: ...

    def store(
        self, *, user_id: str, key: str, confirmation_code: str, ttl_seconds: int
    ) -> None:
        """성공 완료를 기록한다. 이후 재요청은 `done`을 받는다."""

    def store_failure(
        self, *, user_id: str, key: str, failure_code: str, ttl_seconds: int
    ) -> None:
        """실패 완료를 기록한다 (재고 부족·사전 검사 거부). 이후 재요청은
        `failed`와 같은 에러 코드를 받는다 — `PROCESSING`으로 남겨두면
        재요청이 `REQUEST_IN_PROGRESS`로 둔갑한다 (D30)."""

    def release(self, *, user_id: str, key: str) -> None:
        """키를 지운다. **재시도가 의미 있는 실패에서만** — 입력 오류(400),
        잘못된 참조(404), 혼잡(503). 지우면 고친 재시도가 최초 요청이 된다.

        같은 키로 다시 와도 같은 실패가 재현되어야 하는 경우(재고 부족)는
        지우지 않고 `store_failure()`를 부른다 (스펙 2.2절 실패 표 기준)."""


# ── 결제 (2.3절) ────────────────────────────────────────────────────

class PaymentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    transaction_id: str | None = None
    decline_reason: str | None = None


class PaymentPort(Protocol):
    def charge(
        self, *, reservation_id: int, amount: int, idempotency_key: str
    ) -> PaymentResult:
        """거절은 예외가 아니라 반환값이다 — 예약은 그때 CANCELLED로 간다.
        예외는 "판단할 수 없었다"(네트워크 장애)일 때만 던진다.
        **호출은 트랜잭션 밖에서 한다.**"""

    def refund(self, *, transaction_id: str | None) -> None:
        """보상 — 결제 승인 후 전이 경합에서 졌을 때(만료·취소가 먼저 이김)
        결제를 되돌린다 (2.3절 실패 표)."""
