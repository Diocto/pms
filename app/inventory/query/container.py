"""inventory.query 컨텍스트 컨테이너 (F03, 조회 전용).

루트가 주는 네 의존만 선언한다. 배선(공유 파일 `app/containers.py`)은
한 번만 만지기 위해 의존 선언을 먼저 완성해 두고, 프로바이더는
dev-cycle이 진행되며 이 파일 안에서만 채워진다.
"""

from dependency_injector import containers, providers


class InventoryQueryContainer(containers.DeclarativeContainer):
    settings = providers.Dependency()
    redis_client = providers.Dependency()
    transaction_manager = providers.Dependency()
    clock = providers.Dependency()
