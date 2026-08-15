"""유스케이스가 아는 바깥 세계의 전부 — 포트 (스펙 3.6절, D10·D22·D23).

구현은 `infrastructure/`(또는 F02)에 있고 컨테이너가 조립한다. 유스케이스는
어느 구현이 왔는지 모른다. **이 파일의 시그니처는 스펙 3.6절 코드 블록과
한 줄씩 대응한다** — F02가 문서만 보고 구현하는 계약이라, 여기가 스펙과
어긋나면 통합 시점에 TypeError로 드러난다 (3회차 리뷰).

**세션을 받는 포트와 안 받는 포트가 갈리는 이유가 계약의 핵심이다.**
세션을 받는 것(해석기·훅)은 호출부의 트랜잭션에 참여하라는 뜻이고, 받을 수
없으면 자기 세션을 열 수 없다. 안 받는 것(사전 검사)은 트랜잭션이 아직 없고
DB를 건드리지 말라는 뜻이다.
"""

from contextlib import AbstractContextManager
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.inventory.domain.models import Money
from app.reservation.application.commands import CreateReservationCommand, DiscountRef
from app.reservation.domain.enums import ReservationEvent, ReservationStatus
from app.reservation.domain.models import StayPeriod


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

        같은 키로 다시 와도 같은 실패가 재현되어야 하는 경우(재고 부족,
        사전 검사 거부)는 지우지 않고 `store_failure()`를 부른다
        (스펙 2.2절 실패 표 기준)."""


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


# ── 확장 지점 4종 (3.6절) — F02가 구현한다. 시그니처가 곧 계약이다 ────

class ReservationPreCheckHook(Protocol):
    """값비싼 작업에 들어가기 전에 요청을 거를 기회 (D23).

    멱등 키 선점과 입력 검증 뒤, **분산락을 잡기 전에** 호출된다.
    거부는 예외로 표현한다. **세션을 받지 않는다** — 트랜잭션이 아직 없고,
    여기서 DB를 건드리지 말라는 뜻이다.
    """

    def check(self, command: CreateReservationCommand) -> None: ...


class AppliedDiscount(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: DiscountRef                 # 해석 결과가 자기 출처를 안다
    price_per_night: Money


class DiscountResolver(Protocol):
    """할인 참조를 실제 적용 단가로 해석한다. 해석할 수 없으면 None (→ 400
    fail-closed. 정가로 조용히 넘어가지 않는다)."""

    def resolve(
        self,
        session: Session,
        ref: DiscountRef,
        room_type_id: int,
        period: StayPeriod,
    ) -> AppliedDiscount | None: ...


class ReservationCreationHook(Protocol):
    """예약이 만들어진 직후, **같은 트랜잭션에서** 호출된다.

    세션을 첫 인자로 받는 것이 계약의 핵심이다 — 안 주면 구현자가 자기
    세션을 열 수 있고 "함께 커밋하거나 함께 롤백"이 조용히 깨진다.
    구현부는 `session_factory`를 주입받지 않는다.
    """

    def on_created(
        self, session: Session, reservation_id: int, command: CreateReservationCommand
    ) -> None: ...


class ReservationReleaseHook(Protocol):
    """예약에 묶인 부가 자원을 반납한다.

    상태 전이 조건부 UPDATE가 1건 성공했을 때만, 같은 트랜잭션에서
    정확히 한 번 호출된다.
    """

    def on_released(
        self,
        session: Session,
        reservation_id: int,
        from_status: ReservationStatus,
        event: ReservationEvent,
    ) -> None: ...
