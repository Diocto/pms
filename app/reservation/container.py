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
from app.reservation.infrastructure.idempotency import RedisIdempotencyAdapter
from app.reservation.infrastructure.lock import NoOpLockAdapter, RedisLockAdapter
from app.reservation.infrastructure.payment import FakePaymentAdapter
from app.reservation.infrastructure.persistence import MySqlReservationRepository


def _build_lock(settings: Settings, redis_client: redis.Redis):
    return RedisLockAdapter(redis_client) if settings.lock_enabled else NoOpLockAdapter()


class ReservationRuntimeContributor:
    """F01 몫의 실행 상태 보고 (D26).

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

    lock = providers.Singleton(_build_lock, settings, redis_client)
    idempotency = providers.Singleton(RedisIdempotencyAdapter, redis_client)
    payment = providers.Singleton(
        FakePaymentAdapter, decline_rate=settings.provided.payment_decline_rate
    )
    repository = providers.Singleton(MySqlReservationRepository)

    runtime_contributor = providers.Singleton(
        ReservationRuntimeContributor, settings=settings, lock=lock, payment=payment
    )
