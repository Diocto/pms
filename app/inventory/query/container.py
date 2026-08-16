"""inventory.query 컨텍스트 컨테이너 (F03, 조회 전용).

캐시 구현 선택과 값 노출(기여자)이 **같은 프로바이더**를 본다 (D15) —
값은 `false`인데 Redis 구현이 들어가 있는 상태를 만들 자리가 없다.
"""

from dependency_injector import containers, providers

from app.common.config import Settings
from app.inventory.query.application.usecases.list_hotels import ListHotelsUseCase
from app.inventory.query.application.usecases.search_available_rooms import (
    SearchAvailableRoomsUseCase,
)
from app.inventory.query.infrastructure.cache import (
    NoOpAvailabilityCacheAdapter,
    RedisAvailabilityCacheAdapter,
)
from app.inventory.query.infrastructure.persistence import (
    MySqlAvailabilityQueryAdapter,
    MySqlHotelCatalogAdapter,
)
from app.inventory.query.presentation.actuator import SearchRuntimeContributor


def _select_cache(settings: Settings, redis_client):
    if settings.search_cache_enabled:
        return RedisAvailabilityCacheAdapter(
            redis_client, ttl_seconds=settings.search_cache_ttl_seconds
        )
    return NoOpAvailabilityCacheAdapter()


def _stale_tolerance(settings: Settings) -> int:
    # 끄면 모든 응답이 방금 읽은 값이므로 낡음의 상한도 0이다 (계약 문서 3절)
    return settings.search_cache_ttl_seconds if settings.search_cache_enabled else 0


class InventoryQueryContainer(containers.DeclarativeContainer):
    settings = providers.Dependency()
    redis_client = providers.Dependency()
    transaction_manager = providers.Dependency()
    clock = providers.Dependency()

    query_adapter = providers.Singleton(MySqlAvailabilityQueryAdapter)
    hotel_catalog = providers.Singleton(MySqlHotelCatalogAdapter)
    search_cache = providers.Singleton(_select_cache, settings, redis_client)
    stale_tolerance_seconds = providers.Factory(_stale_tolerance, settings)

    search_available_rooms = providers.Factory(
        SearchAvailableRoomsUseCase,
        transaction_manager=transaction_manager,
        query_adapter=query_adapter,
        cache=search_cache,
        clock=clock,
        stale_tolerance_seconds=stale_tolerance_seconds,
    )

    list_hotels = providers.Factory(
        ListHotelsUseCase,
        transaction_manager=transaction_manager,
        catalog=hotel_catalog,
    )

    runtime_contributor = providers.Singleton(
        SearchRuntimeContributor, settings=settings, cache=search_cache
    )
