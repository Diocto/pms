"""테스트 공용 픽스처.

**컨테이너는 테스트 전체에서 하나만 띄운다.** 세션 스코프로 만들고 재사용해야
전체 시간이 감당된다. 테스트마다 MySQL을 띄우면 통합 테스트를 안 돌리게 된다.

**SQLite를 쓰지 않는다.** 행 수준 락이 없고 `SELECT ... FOR UPDATE`를 사실상
무시하며 CHECK 동작도 다르다. 동시성이 주제인 프로젝트에서 SQLite로 검증하면
그 검증이 거짓이다. 느린 건 타협 대상이 아니다.
"""

import os
from collections.abc import Iterator
from pathlib import Path

# macOS의 Docker Desktop은 사용자별 소켓(~/.docker/run/docker.sock)을 컨테이너 안으로
# 마운트하지 못한다. testcontainers는 정리용 사이드카(Ryuk)에 소켓을 마운트해서
# 테스트가 죽어도 컨테이너가 남지 않게 하는데, 바로 그 마운트가 여기서 막힌다.
# 표준 경로 /var/run/docker.sock이 같은 소켓을 가리키는 심볼릭 링크이고 Docker Desktop이
# 이 경로만 마운트할 수 있으므로, 컨테이너에 넘길 경로만 바꿔준다.
# testcontainers가 import 시점에 설정을 읽으므로 import보다 먼저 와야 한다.
os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from testcontainers.community.mysql import MySqlContainer  # noqa: E402
from testcontainers.community.redis import RedisContainer  # noqa: E402

from app.main import create_app  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_migrations(url: str) -> None:
    """실제 DB에 마이그레이션을 끝까지 적용한다.

    모델에서 테이블을 자동 생성하지 않는다. 스키마의 진실은 마이그레이션이고,
    자동 생성으로 테스트하면 마이그레이션이 틀려도 초록불이 켜진다.
    """
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # ConfigParser가 %를 서식 문자로 읽으므로 escape한다.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def mysql_container() -> Iterator[MySqlContainer]:
    with MySqlContainer("mysql:8.4") as container:
        yield container


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7.4-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(mysql_container: MySqlContainer) -> str:
    """마이그레이션까지 끝난 DB의 접속 URL.

    이 픽스처를 받는 것이 곧 "스키마가 준비된 DB를 받는다"는 뜻이다.
    """
    url = _with_pymysql_driver(mysql_container.get_connection_url())
    run_migrations(url)
    return url


def _with_pymysql_driver(url: str) -> str:
    """드라이버를 URL에 명시한다.

    `mysql://`만 적으면 SQLAlchemy가 기본 드라이버인 MySQLdb(C 확장)를 찾는다.
    우리는 순수 파이썬 구현인 PyMySQL을 쓰므로 어디서 만든 URL이든 여기서 맞춘다.
    """
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+pymysql://", 1)
    return url


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """인프라 없이 앱만 띄운다. DB가 필요한 API 테스트는 `database_url`을 함께 받는다."""
    with TestClient(create_app()) as test_client:
        yield test_client
