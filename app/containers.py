"""루트 컨테이너.

**조립은 컨테이너가 전담한다.** 유스케이스가 포트의 구현체를 직접 만들지 않는다.
무엇이 들어오는지는 컨테이너가 정한다.

컨텍스트(reservation, inventory, promotion)는 각자 `container.py`를 갖고,
루트가 그것들을 묶는다. 그래야 feature 하나를 들어내도 나머지가 돈다.
컨텍스트 컨테이너는 각 feature 세션이 자기 회차에 추가한다.
"""

import redis
from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.common.clock import SystemClock
from app.common.config import Settings
from app.common.db import TransactionManager
from app.reservation.container import ReservationContainer


def _build_redis(settings: Settings) -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=False)


def _build_engine(settings: Settings):
    return create_engine(settings.database_url, pool_pre_ping=True)


class AppContainer(containers.DeclarativeContainer):
    # 설정은 여기서 한 번 만들어 필요한 곳에 나눠준다. 두 곳에서 따로 읽지 않는다.
    settings = providers.Singleton(Settings)

    clock = providers.Singleton(SystemClock)

    redis_client = providers.Singleton(_build_redis, settings)
    engine = providers.Singleton(_build_engine, settings)
    session_factory = providers.Singleton(sessionmaker, bind=engine)
    transaction_manager = providers.Singleton(TransactionManager, session_factory)

    reservation = providers.Container(
        ReservationContainer,
        settings=settings,
        redis_client=redis_client,
        transaction_manager=transaction_manager,
        clock=clock,
    )

    # 컨텍스트별 실행 상태 기여 (D26). F02·F03이 자기 기여자를 여기 추가한다 —
    # 구현이 0개인 컨텍스트는 자연히 응답에 나오지 않는다
    runtime_contributors = providers.List(reservation.runtime_contributor)
