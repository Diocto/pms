"""예약 생성 유스케이스 — 이 프로젝트의 심장 (스펙 2.2절, 4.1절의 열두 줄).

순서가 곧 계약이다. 락이 트랜잭션 밖에 있다는 사실, 사전 검사가 락보다
앞이라는 사실, 멱등 저장이 커밋 뒤라는 사실이 전부 `execute()` 한 함수에서
눈으로 읽힌다 — 데코레이터를 기각한 이유가 이것이다 (D28).

```
멱등 키 선점 → (입력 검증) → [PreCheckHook] → 락 획득
  ┌─ 트랜잭션 ────────────────────────────┐
  │ [DiscountResolver] → 가격 확정        │
  │ → 재고 차감 → 예약 INSERT             │
  │ → [CreationHook]                     │
  └──────────────────────────────────────┘
  커밋 → 락 해제 → 멱등 결과 저장
```

입력 검증 주의: VO 불변식(기간·인원)은 Command를 만드는 라우터에서
이미 터진다 — 그 400은 멱등 키를 선점하기 전이라 키가 애초에 없다. 결과적으로
"입력 오류는 키를 남기지 않는다"는 계약(2.2절)과 같은 끝 상태다.
"""

import logging

from app.common.clock import Clock
from app.common.db import TransactionManager
from app.common.errors import ConflictError, InvalidRequestError, NotFoundError
from app.inventory.domain.errors import InsufficientInventoryError
from app.inventory.domain.models import Money, RoomType
from app.inventory.domain.repositories import InventoryRepository
from app.reservation.application.commands import (
    CreateReservationCommand,
    ReservationResult,
)
from app.reservation.application.errors import (
    DuplicateConfirmationCodeError,
    DuplicateIdempotencyKeyError,
    LockAcquisitionError,
    RequestInProgressError,
)
from app.reservation.application.ports import (
    AppliedDiscount,
    IdempotencyPort,
    LockPolicy,
    ReservationExtensions,
)
from app.reservation.domain.models import Reservation
from app.reservation.domain.repositories import ReservationRepository
from app.reservation.domain.services import generate_confirmation_code

logger = logging.getLogger(__name__)

_CODE_RETRY = 3  # 확인번호 무작위 8자 충돌 시 재생성 상한 (D7)


class CreateReservationUseCase:
    def __init__(
        self,
        *,
        tx: TransactionManager,
        idempotency: IdempotencyPort,
        inventory_repository: InventoryRepository,
        reservation_repository: ReservationRepository,
        clock: Clock,
        hold_minutes: int,
        lock_policy: LockPolicy,
        extensions: ReservationExtensions,
    ) -> None:
        # 파라미터는 종류별 묶음으로 받는다 (ADR-0064) — 락의 사용법은
        # LockPolicy가, 확장 지점 셋은 ReservationExtensions가 든다.
        self._tx = tx
        self._lock_policy = lock_policy
        self._idempotency = idempotency
        self._inventory = inventory_repository
        self._reservations = reservation_repository
        self._clock = clock
        self._hold_minutes = hold_minutes
        self._extensions = extensions

    def execute(self, command: CreateReservationCommand) -> ReservationResult:
        ttl_seconds = self._hold_minutes * 60

        # ── 멱등 키 선점 (트랜잭션 밖, Redis) ──────────────────────────
        claim = self._idempotency.claim(
            user_id=command.user_id, key=command.idempotency_key,
            ttl_seconds=ttl_seconds,
        )
        if claim.outcome == "done":
            return self._replay(claim.confirmation_code)
        if claim.outcome == "processing":
            raise RequestInProgressError("같은 요청이 처리 중입니다")
        if claim.outcome == "failed":
            # 같은 키 재요청은 같은 실패를 받는다 (D30). 코드가 곧 저장된 결과다
            raise ConflictError("이전 요청과 같은 결과입니다", code=claim.failure_code)

        try:
            # ── 사전 검사 훅 — 락보다 앞이다 (D23). 세션도 락도 아직 없다 ──
            self._run_pre_checks(command)

            period = command.line.stay_period
            now = self._clock.now().replace(tzinfo=None)  # DATETIME은 naive KST다
            today = self._clock.today()

            # ── 락 (밖) → 트랜잭션 (안) — 순서가 뒤집히면 커밋 전에 풀린다 ──
            # 키 규약·대기·수명은 LockPolicy 안에 있다. 해제는 with가 한다
            idempotency_conflict = False
            with self._lock_policy.hold_inventory(
                room_type_id=command.line.room_type_id,
                stay_dates=period.occupied_dates(),
            ):
                for attempt in range(_CODE_RETRY):
                    try:
                        result = self._create_in_transaction(
                            command, now=now, today=today
                        )
                        break
                    except DuplicateConfirmationCodeError:
                        # 무작위 8자 충돌 — 새 코드로 재생성 (D7)
                        if attempt == _CODE_RETRY - 1:
                            raise
                        continue
                    except DuplicateIdempotencyKeyError:
                        # Redis가 뚫린 상황 — DB UK가 정답이다 (D9).
                        # 재생 조회·저장은 락 밖에서 한다 — 락을 쥔 채
                        # Redis·재조회를 하면 장애 국면에 락 보유가 늘어난다
                        idempotency_conflict = True
                        break
            if idempotency_conflict:
                logger.warning(
                    "멱등 UK 충돌 — Redis 우회 감지. 500이 아니라 기존 예약으로 "
                    "응답한다 (T54) user=%s", command.user_id,
                )
                return self._replay_by_idempotency(command)
            # ── 커밋·락 해제 완료 후 멱등 결과 저장 (Redis, 밖) ────────────
            self._idempotency.store(
                user_id=command.user_id, key=command.idempotency_key,
                confirmation_code=result.confirmation_code, ttl_seconds=ttl_seconds,
            )
            return result

        except InsufficientInventoryError as error:
            # 재고 부족은 키를 남기되 실패로 완료 표시한다 — 같은 키 재요청이
            # 같은 409를 받는다 (D30)
            self._idempotency.store_failure(
                user_id=command.user_id, key=command.idempotency_key,
                failure_code=error.code, ttl_seconds=ttl_seconds,
            )
            raise
        except (InvalidRequestError, NotFoundError, LockAcquisitionError):
            # 재시도가 의미 있는 실패(400·404·503) — 키를 지워 고친 재시도가
            # 최초 요청이 되게 한다 (2.2절 실패 표)
            self._idempotency.release(
                user_id=command.user_id, key=command.idempotency_key
            )
            raise
        except ConflictError as error:
            # 사전 검사 훅의 거부(선착순 특가의 409류) — 재고 부족과 같은 성격이라
            # 실패로 완료 표시한다. 같은 키 재요청이 같은 409를 받는다 (D30)
            if error.code is not None:
                self._idempotency.store_failure(
                    user_id=command.user_id, key=command.idempotency_key,
                    failure_code=error.code, ttl_seconds=ttl_seconds,
                )
            raise
        except Exception:
            # 예상 못 한 실패(500) — 아무것도 커밋되지 않았으므로 키를 지워
            # 재시도가 최초 요청이 되게 한다 (D31). PROCESSING으로 방치하면
            # 사용자가 TTL 10분간 가짜 409 루프에 갇힌다
            self._idempotency.release(
                user_id=command.user_id, key=command.idempotency_key
            )
            raise

    # ── 트랜잭션 안 ────────────────────────────────────────────────────

    def _create_in_transaction(
        self, command: CreateReservationCommand, *, now, today
    ) -> ReservationResult:
        line = command.line
        with self._tx.write() as session:
            # 이 조회는 잠그지 않는다 — FOR UPDATE 없는 단순 SELECT라 객실타입
            # 전체는 물론 이 행조차 잠기지 않는다. 잠금은 아래 deduct의 날짜별
            # 재고 행 UPDATE에서만 생긴다 (행 단위, 날짜 오름차순)
            room_type = session.get(RoomType, line.room_type_id)
            if room_type is None:
                raise NotFoundError(f"객실타입 {line.room_type_id}이 없습니다")

            price_per_night = self._resolve_price(session, command, room_type)

            reservation = Reservation.create(
                user_id=command.user_id,
                idempotency_key=command.idempotency_key,
                room_type=room_type,
                period=line.stay_period,
                room_count=line.room_count,
                guest_count=line.guest_count,
                price_per_night=price_per_night,
                confirmation_code=generate_confirmation_code(
                    check_in=line.stay_period.check_in, room_type=room_type
                ),
                today=today,
                now=now,
                hold_minutes=self._hold_minutes,
            )

            # 가격 확정 → 재고 차감 → INSERT → 훅 (3.6절 호출 순서)
            self._inventory.deduct(
                session,
                room_type_id=line.room_type_id,
                stay_dates=line.stay_period.occupied_dates(),
                room_count=line.room_count,
                now=now,
            )
            self._reservations.insert(session, reservation)
            self._run_creation_hooks(session, reservation.id, command)

            return ReservationResult.model_validate(reservation)

    # ── 확장 지점 실행 (3.6절) ─────────────────────────────────────────
    # 훅의 계약(언제 불리고, 세션을 받는가)은 ports.py의 Protocol 문서가
    # 진실이다. 여기 이름은 "언제"만 말한다. 구현이 0개면 아무 일도 없다

    def _run_pre_checks(self, command: CreateReservationCommand) -> None:
        """값비싼 작업 전의 거부 기회 — 멱등 선점 뒤, 분산락 전 (D23)."""
        for hook in self._extensions.pre_check:
            hook.check(command)

    def _run_creation_hooks(
        self, session, reservation_id: int, command: CreateReservationCommand
    ) -> None:
        """예약 INSERT 직후, 같은 트랜잭션 안 — 함께 커밋되거나 함께 롤백된다."""
        for hook in self._extensions.creation:
            hook.on_created(session, reservation_id, command)

    def _resolve_price(self, session, command, room_type: RoomType) -> Money:
        if not command.discounts:
            return Money(amount=room_type.base_price)  # 정가 예약
        if len(command.discounts) > 1:
            raise InvalidRequestError("할인은 하나만 적용할 수 있습니다")

        ref = command.discounts[0]
        for resolver in self._extensions.discount_resolvers:
            applied = resolver.resolve(
                session, ref, command.line.room_type_id, command.line.stay_period
            )
            if applied is not None:
                return applied.price_per_night
        # 해석 실패는 400이다 — 정가로 조용히 넘어가면 사용자가 기대한 금액보다
        # 더 청구하게 된다 (fail-closed, 3.6절)
        raise InvalidRequestError(f"할인을 해석할 수 없습니다: {ref.reference}")

    # ── 멱등 재요청 ────────────────────────────────────────────────────

    def _replay(self, confirmation_code: str) -> ReservationResult:
        with self._tx.read() as session:
            reservation = self._reservations.find_by_code(session, confirmation_code)
            if reservation is None:
                # Redis에는 DONE인데 DB에 없다 — 있을 수 없는 상태다. 조용히 넘기지 않는다
                raise NotFoundError("저장된 예약을 찾을 수 없습니다")
            # 세션이 닫히기 전에 옮긴다 — rollback이 객체 속성을 만료시킨다
            result = ReservationResult.model_validate(reservation)
        return result.model_copy(update={"replayed": True})

    def _replay_by_idempotency(
        self, command: CreateReservationCommand
    ) -> ReservationResult:
        with self._tx.read() as session:
            reservation = self._reservations.find_by_idempotency(
                session,
                user_id=command.user_id,
                idempotency_key=command.idempotency_key,
            )
            if reservation is None:
                raise NotFoundError("기존 예약을 찾을 수 없습니다")
            result = ReservationResult.model_validate(reservation)  # 세션 안에서 옮긴다
        self._idempotency.store(
            user_id=command.user_id, key=command.idempotency_key,
            confirmation_code=result.confirmation_code,
            ttl_seconds=self._hold_minutes * 60,
        )
        return result.model_copy(update={"replayed": True})
