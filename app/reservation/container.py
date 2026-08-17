"""reservation 컨텍스트의 조립 (스펙 4.1절, D17·D26).

락 구현은 `PMS_LOCK_ENABLED` 하나로 갈린다 — 끌 수 없는 층은 살아 있는지
확인할 방법이 없다. **바꿔 끼우는 곳은 여기 한 곳뿐이고** 유스케이스는
어느 쪽이 왔는지 모른다.

`runtime_contributor`가 노출하는 값은 락 구현이 실제로 쓰는 **같은
프로바이더**에서 나온다 — 검증 장치가 검증 대상과 다른 곳을 보면 검증이
아니다 (D26).
"""

import redis
from dependency_injector import containers, providers

from app.common.config import Settings
from app.common.runtime_report import RuntimeReport
from app.inventory.infrastructure.persistence import MySqlInventoryRepository
from app.reservation.application.usecases.create_reservation import (
    CreateReservationUseCase,
)
from app.reservation.application.usecases.transition_reservation import (
    CancelReservationUseCase,
    CheckInOutUseCase,
    ConfirmReservationUseCase,
    ExpireReservationsUseCase,
    GetReservationUseCase,
    ListReservationsUseCase,
)
from app.reservation.application.ports import LockPolicy, ReservationExtensions
from app.reservation.infrastructure.idempotency import RedisIdempotencyAdapter
from app.reservation.infrastructure.lock import NoOpLockAdapter, RedisLockAdapter
from app.reservation.infrastructure.payment import FakePaymentAdapter
from app.reservation.infrastructure.persistence import MySqlReservationRepository


def _build_lock(
    settings: Settings, redis_client: redis.Redis
) -> RedisLockAdapter | NoOpLockAdapter:
    return RedisLockAdapter(redis_client) if settings.lock_enabled else NoOpLockAdapter()


def _lock_wait_seconds(settings: Settings) -> float:
    """밀리초 설정을 포트 계약(초)으로 바꾸는 **유일한 변환 지점.**

    유스케이스는 이 프로바이더만 주입받는다. `settings.lock_wait_millis`를
    직접 `wait_s`에 넣으면 200초 대기가 되는데, 그 실수를 잡을 검증이
    어디에도 없다 (3회차 리뷰) — 그래서 변환을 조립에 박는다.
    """
    return settings.lock_wait_millis / 1000


class ReservationRuntimeContributor:
    """예약 코어 몫의 실행 상태 보고 (D26).

    `implementations` 값은 손으로 적지 않고 **실물에서 뽑는다** —
    `type(...).__name__`. 문자열을 손으로 적으면 배선과 어긋날 자리가 된다.
    """

    def __init__(self, settings: Settings, lock: object, payment: object) -> None:
        self._settings = settings
        self._lock = lock
        self._payment = payment

    def report(self) -> RuntimeReport:
        return RuntimeReport(
            load_test={
                # 키는 조작자가 셸에 치는 환경변수 이름 그대로다 (D26)
                "PMS_LOCK_ENABLED": self._settings.lock_enabled,
                "PMS_LOCK_WAIT_MILLIS": self._settings.lock_wait_millis,
                "PMS_LOCK_TTL_SECONDS": self._settings.lock_ttl_seconds,
                "PMS_RESERVATION_HOLD_MINUTES": self._settings.reservation_hold_minutes,
                "PMS_RESERVATION_EXPIRE_SCAN_SECONDS": (
                    self._settings.reservation_expire_scan_seconds
                ),
                "PMS_PAYMENT_DECLINE_RATE": self._settings.payment_decline_rate,
            },
            implementations={
                "LockPort": type(self._lock).__name__,
                "PaymentPort": type(self._payment).__name__,
            },
        )


class ReservationContainer(containers.DeclarativeContainer):
    # 루트가 넘겨준다 — 설정을 두 곳에서 따로 읽지 않는다
    settings = providers.Dependency(instance_of=Settings)
    redis_client = providers.Dependency()
    transaction_manager = providers.Dependency()
    clock = providers.Dependency()

    # 잠금 없는 Singleton 금지 (D37, T90) — 냉시동 동시 접근에 여럿 만들어진다
    lock = providers.ThreadSafeSingleton(_build_lock, settings, redis_client)
    lock_wait_s = providers.Callable(_lock_wait_seconds, settings)
    idempotency = providers.ThreadSafeSingleton(RedisIdempotencyAdapter, redis_client)
    payment = providers.ThreadSafeSingleton(
        FakePaymentAdapter, decline_rate=settings.provided.payment_decline_rate
    )
    repository = providers.ThreadSafeSingleton(MySqlReservationRepository)
    inventory_repository = providers.ThreadSafeSingleton(MySqlInventoryRepository)

    # 확장 지점 — 선착순 특가가 자기 구현을 추가한다. 0개면 빈 리스트라 아무 일도
    # 일어나지 않고, 선착순 특가 병합 전에도 코어가 그대로 돈다 (T74)
    pre_check_hooks = providers.List()
    creation_hooks = providers.List()
    release_hooks = providers.List()
    discount_resolvers = providers.List()

    # 종류별 묶음 (ADR-0064). Factory여야 한다 — 테스트가 위의 낱개
    # 프로바이더를 override하면 다음 생성에서 그대로 반영돼야 하므로,
    # 여기서 값을 굳히면 안 된다
    lock_policy = providers.Factory(
        LockPolicy,
        lock=lock,
        wait_s=lock_wait_s,
        ttl_s=settings.provided.lock_ttl_seconds,
    )
    extensions = providers.Factory(
        ReservationExtensions,
        pre_check=pre_check_hooks,
        creation=creation_hooks,
        discount_resolvers=discount_resolvers,
    )

    runtime_contributor = providers.ThreadSafeSingleton(
        ReservationRuntimeContributor, settings=settings, lock=lock, payment=payment
    )

    create_reservation = providers.Factory(
        CreateReservationUseCase,
        tx=transaction_manager,
        idempotency=idempotency,
        inventory_repository=inventory_repository,
        reservation_repository=repository,
        clock=clock,
        hold_minutes=settings.provided.reservation_hold_minutes,
        lock_policy=lock_policy,
        extensions=extensions,
    )

    _transition_deps = dict(
        tx=transaction_manager,
        inventory_repository=inventory_repository,
        reservation_repository=repository,
        clock=clock,
        release_hooks=release_hooks,
    )
    confirm_reservation = providers.Factory(
        ConfirmReservationUseCase, payment=payment, **_transition_deps
    )
    cancel_reservation = providers.Factory(
        CancelReservationUseCase, **_transition_deps
    )
    expire_reservations = providers.Factory(
        ExpireReservationsUseCase,
        batch_size=100,  # 한 주기의 처리 상한 — 조립에서 보이게 명시한다
        **_transition_deps,
    )
    check_in_out = providers.Factory(CheckInOutUseCase, **_transition_deps)
    get_reservation = providers.Factory(GetReservationUseCase, **_transition_deps)
    list_reservations = providers.Factory(ListReservationsUseCase, **_transition_deps)
