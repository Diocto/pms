"""Alembic 실행 환경.

**스키마의 진실은 마이그레이션이지 모델 클래스가 아니다.** 테스트에서도 테이블을
자동 생성(`create_all`)하지 않고 이 파일을 통해 실제로 마이그레이션을 돌린다.
자동 생성으로 테스트하면 마이그레이션이 틀려도 초록불이 켜지고, CHECK 제약과
인덱스가 실제로 걸렸는지는 끝까지 확인되지 않는다.

**리비전 번호는 feature별로 대역을 나눠 쓴다.** 병렬 세션이 같은 번호를 만들면
머지할 때 충돌한다. 대역은 `docs/architecture/parallel-work.md`에 있다.
번호는 자동 생성에 맡기지 않고 직접 지정한다.

    alembic revision --rev-id 001 -m "예약_재고_기본_스키마"
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app.common.config import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 접속 정보의 출처는 Settings 하나다. 테스트는 컨테이너 URL을 넣어주므로
# 이미 지정돼 있으면 그것을 존중한다.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", Settings().database_url)

# 각 컨텍스트의 domain/models.py를 여기서 import해야 autogenerate가 인식한다.
import app.inventory.domain.models  # noqa: E402, F401
import app.reservation.domain.models  # noqa: E402, F401

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
