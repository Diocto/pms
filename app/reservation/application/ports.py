"""유스케이스가 아는 바깥 세계의 전부 — 포트 (스펙 3.6절, D10·D22·D23).

구현은 `infrastructure/`에 있고 컨테이너가 조립한다. 유스케이스는 어느 구현이
왔는지 모른다.

**세션을 받는 포트와 안 받는 포트가 갈리는 이유가 계약의 핵심이다.**
세션을 받는 것(해석기·훅)은 호출부의 트랜잭션에 참여하라는 뜻이고, 받을 수
없으면 자기 세션을 열 수 없다. 안 받는 것(사전 검사)은 트랜잭션이 아직 없고
DB를 건드리지 말라는 뜻이다.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.inventory.domain.models import Money


# ── 분산락 (3.3절, D10) ─────────────────────────────────────────────

class LockPort(Protocol):
    def acquire_all(
        self, keys: list[str], *, wait_s: float, ttl_s: int
    ) -> AbstractContextManager[None]:
        """받은 키를 **정렬해서** 전부 잠근다. 호출부는 순서를 신경 쓸 기회조차
        없다 — 넘기는 것은 집합이고 순서는 구현의 몫이다.
        하나라도 실패하면 `LockAcquisitionError` (503)."""


# ── 멱등성 (3.4절, D9·D18) ──────────────────────────────────────────

class IdempotencyClaim(BaseModel):
    """선점 시도의 결과 3상태.

    - `acquired` — 최초 요청. 처리 후 `store()`를 불러야 한다
    - `processing` — 같은 키가 처리 중. 409 `REQUEST_IN_PROGRESS`
    - `done` — 이미 처리됨. `confirmation_code`로 조회해 200 + 같은 본문
    """

    model_config = ConfigDict(frozen=True)

    outcome: Literal["acquired", "processing", "done"]
    confirmation_code: str | None = None


class IdempotencyPort(Protocol):
    def claim(self, *, user_id: str, key: str, ttl_seconds: int) -> IdempotencyClaim: ...

    def store(
        self, *, user_id: str, key: str, confirmation_code: str, ttl_seconds: int
    ) -> None:
        """처리 완료를 기록한다. 이후 재요청은 `done`을 받는다."""

    def release(self, *, user_id: str, key: str) -> None:
        """키를 지운다. **입력 오류(400)일 때만** — 고쳐서 다시 보내는 것이
        정상이다. 재고 부족(409)은 지우지 않는다 — 같은 키로 다시 와도
        결과가 같다."""


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


# ── 확장 지점 4종 (3.6절) — F02가 구현한다 ───────────────────────────

class DiscountType(BaseModel):
    """(자리 표시) commands.py로 이동 예정 — 4회차."""


class ReservationPreCheckHook(Protocol):
    """값비싼 작업에 들어가기 전에 요청을 거를 기회 (D23).

    멱등 키 선점과 입력 검증 뒤, **분산락을 잡기 전에** 호출된다.
    거부는 예외로 표현한다. **세션을 받지 않는다** — 트랜잭션이 아직 없고,
    여기서 DB를 건드리지 말라는 뜻이다.
    """

    def check(self, command: object) -> None: ...


class AppliedDiscount(BaseModel):
    model_config = ConfigDict(frozen=True)

    price_per_night: Money


class DiscountResolver(Protocol):
    """할인 참조를 실제 적용 단가로 해석한다. 해석할 수 없으면 None (→ 400
    fail-closed. 정가로 조용히 넘어가지 않는다)."""

    def resolve(
        self,
        session: Session,
        *,
        reference: object,
        room_type_id: int,
        check_in: date,
        check_out: date,
    ) -> AppliedDiscount | None: ...


class ReservationCreationHook(Protocol):
    """예약이 만들어진 직후, **같은 트랜잭션에서** 호출된다.

    세션을 첫 인자로 받는 것이 계약의 핵심이다 — 안 주면 구현자가 자기
    세션을 열 수 있고 "함께 커밋하거나 함께 롤백"이 조용히 깨진다.
    구현부는 `session_factory`를 주입받지 않는다.
    """

    def on_created(
        self, session: Session, reservation_id: int, command: object
    ) -> None: ...


class ReservationReleaseHook(Protocol):
    """예약에 묶인 부가 자원을 반납한다.

    상태 전이 조건부 UPDATE가 1건 성공했을 때만, 같은 트랜잭션에서
    정확히 한 번 호출된다.
    """

    def on_released(
        self, session: Session, reservation_id: int, from_status: str, event: str
    ) -> None: ...
