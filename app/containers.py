"""루트 컨테이너.

**조립은 컨테이너가 전담한다.** 유스케이스가 어댑터를 직접 만들지 않는다.

컨텍스트(reservation, inventory, promotion)는 각자 `container.py`를 갖고,
루트가 그것들을 묶는다. 그래야 feature 하나를 들어내도 나머지가 돈다.
컨텍스트 컨테이너는 각 feature 세션이 자기 회차에 추가한다.
"""

from dependency_injector import containers, providers

from app.common.clock import SystemClock
from app.common.config import Settings


class AppContainer(containers.DeclarativeContainer):
    # 설정은 여기서 한 번 만들어 필요한 곳에 나눠준다. 두 곳에서 따로 읽지 않는다.
    settings = providers.Singleton(Settings)

    clock = providers.Singleton(SystemClock)
