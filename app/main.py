"""FastAPI 앱 생성.

**핸들러는 `async def`가 아니라 `def`로 쓴다.** FastAPI가 `def` 핸들러를 스레드풀에서
실행하므로 DB 바운드 작업에 실제 병렬성이 나온다. 이 프로젝트가 증명하려는 것은
처리량이 아니라 "잔여 10에 200 요청이 몰려도 성공이 정확히 10"이고, 경합은
애플리케이션 스레드가 아니라 DB 행에서 일어난다.

앱을 모듈 수준 전역이 아니라 팩토리로 만든다. 테스트가 매번 깨끗한 앱을 만들 수 있고,
컨테이너를 `override`로 갈아끼울 자리가 생긴다.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.common.error_handlers import register_error_handlers
from app.containers import AppContainer
from app.inventory.query.presentation.router import router as availability_router
from app.reservation.presentation.actuator import router as actuator_router
from app.reservation.presentation.router import router as reservation_router
from app.reservation.presentation.scheduler import ExpireScheduler


def create_app() -> FastAPI:
    container = AppContainer()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = ExpireScheduler(
            usecase_factory=container.reservation.expire_reservations,
            interval_seconds=container.settings().reservation_expire_scan_seconds,
        )
        scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(title="PMS 숙박 예약 시스템", version="0.1.0", lifespan=lifespan)
    app.state.container = container

    register_error_handlers(app)
    app.include_router(actuator_router)
    app.include_router(reservation_router)
    app.include_router(availability_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """앱이 떠 있는지만 본다. DB·Redis 연결은 보지 않는다.

        의존 인프라까지 확인하는 것은 별개의 관심사다. 여기에 DB 조회를 넣으면
        부하 상황에서 헬스체크가 커넥션을 잡아먹는다.
        """
        return {"status": "UP"}

    return app


app = create_app()
