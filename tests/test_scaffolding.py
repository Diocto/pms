"""스캐폴딩이 실제로 도는지 확인한다.

리비전이 0개인 지금도 이 테스트들은 의미가 있다. 배선이 틀렸을 때
**리비전을 처음 추가하는 세션이 자기 SQL과 배선을 함께 의심하는 상황**을 막는다.
"""

from sqlalchemy import create_engine, text

from app.common.clock import SystemClock
from app.common.config import Settings


def test_마이그레이션_파이프라인이_실제_MySQL_8_4에서_끝까지_돈다(database_url: str) -> None:
    """`database_url` 픽스처가 이미 `alembic upgrade head`를 돌렸다.

    확인하는 것: env.py가 import되고, Settings를 읽고, 컨테이너로 뜬 진짜 MySQL에
    접속해 트랜잭션을 연다는 것. 여기까지가 나머지 세 세션이 물려받는 부분이다.

    확인하지 않는 것: 스키마의 내용. 리비전이 생기면 그때 테이블과 제약을 본다.
    """
    engine = create_engine(database_url)

    with engine.connect() as connection:
        version = connection.execute(text("SELECT VERSION()")).scalar_one()

    assert version.startswith("8.4"), f"MySQL 8.4가 아니다: {version}"


def test_설정은_환경변수_이름_그대로_뒤집힌다(monkeypatch) -> None:
    """부하테스트가 스위치를 끄는 방법이 이것 하나다.

    필드 이름이 아니라 이 환경변수 이름이 계약이라, 이름이 바뀌면 여기서 깨진다.
    """
    monkeypatch.setenv("PMS_LOCK_ENABLED", "false")

    assert Settings().lock_enabled is False


def test_분산락은_기본적으로_켜져_있다() -> None:
    """실행 설정 — 환경변수 없이 기동하면 lock_enabled 기본값이 켜짐(True)이다.
    기본이 꺼짐이면 평범한 기동에서 1차 방어선이 소리 없이 빠진다."""
    assert Settings().lock_enabled is True


def test_시계는_한국_시간대를_기준으로_현재_시각을_준다() -> None:
    """서버가 UTC로 날짜를 계산하면 오전 9시 이전 요청이 전날 재고를 차감한다."""
    now = SystemClock().now()

    assert str(now.tzinfo) == "Asia/Seoul"
