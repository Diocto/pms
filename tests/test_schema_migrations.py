"""마이그레이션·스키마·시드 검증 (테스트 T27·T28·T29, 스펙 1.6~1.9).

T28이 이 셋의 핵심이다 — 모델(SQLModel metadata)과 실제 스키마(마이그레이션이
만든 것)를 autogenerate 비교로 대조한다. **스키마의 진실은 마이그레이션이고
모델이 아니다.** 둘이 어긋나면 모델로 짠 코드가 없는 컬럼을 만지는데, 그
어긋남은 조용하다.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

# 모델을 metadata에 올리기 위한 import. 지우면 T28이 "테이블 전부 없음"으로 깨진다
import app.inventory.domain.models  # noqa: F401
import app.reservation.domain.models  # noqa: F401


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar_one()


def test_T27_F01_마이그레이션이_전부_적용됐다(engine):
    """현재 리비전의 조상에 052가 있는지 본다.

    `version_num == "052"` 단정은 "052가 전체 체인의 head다"라서, F02가
    `201_…`을 붙이는 순간 F01 스키마는 멀쩡한데 빨개진다 (리뷰 지적).
    검증할 것은 "F01 것이 적용됐다"이므로 조상 관계로 본다.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    current = _scalar(engine, "SELECT version_num FROM alembic_version")

    project_root = Path(__file__).resolve().parent.parent
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    script = ScriptDirectory.from_config(config)
    ancestors = {
        revision.revision for revision in script.iterate_revisions(current, "base")
    }
    assert "052_seed_daily_inventory" in ancestors


def test_T28_모델과_실제_스키마의_autogenerate_diff가_비어_있다(engine):
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diffs = compare_metadata(context, SQLModel.metadata)
    assert diffs == [], f"모델과 스키마가 어긋난다: {diffs}"


class Test_T29_시드_계약:
    """스펙 1.9절의 숫자 그대로. F02·F03·F04가 이 값을 상수로 박는다."""

    def test_호텔_2곳(self, engine):
        assert _scalar(engine, "SELECT COUNT(*) FROM hotel") == 2

    def test_객실타입_5종(self, engine):
        assert _scalar(engine, "SELECT COUNT(*) FROM room_type") == 5

    def test_재고_450행(self, engine):
        assert _scalar(engine, "SELECT COUNT(*) FROM room_daily_inventory") == 450

    def test_날짜_범위는_고정이다(self, engine):
        low = _scalar(engine, "SELECT MIN(stay_date) FROM room_daily_inventory")
        high = _scalar(engine, "SELECT MAX(stay_date) FROM room_daily_inventory")
        assert str(low) == "2026-08-01"
        assert str(high) == "2026-10-29"

    def test_경합_실험용_소량_재고_타입이_있다(self, engine):
        quantity = _scalar(
            engine, "SELECT total_quantity FROM room_type WHERE id = 3"
        )
        assert quantity == 10  # 스위트. 부하테스트의 경합 대상

    def test_호텔_계약_전체를_고정한다(self, engine):
        # id 한 칸만 보면 나머지 매핑이 무방비다 (리뷰 지적). 표를 통째로 박는다
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name FROM hotel ORDER BY id")
            ).all()
        assert rows == [(1, "서울 그랜드 호텔"), (2, "부산 오션뷰 호텔")]

    def test_객실타입_계약_전체를_고정한다(self, engine):
        # 스펙 1.9절 (3) 표 그대로. capacity가 틀리면 F02·F03의 정원
        # 검증 상수가 통합 시점에 조용히 어긋난다
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, hotel_id, name, capacity, total_quantity, base_price"
                    " FROM room_type ORDER BY id"
                )
            ).all()
        assert rows == [
            (1, 1, "스탠다드", 2, 100, 150000),
            (2, 1, "디럭스", 3, 50, 250000),
            (3, 1, "스위트", 4, 10, 600000),
            (4, 2, "오션뷰 스탠다드", 2, 80, 180000),
            (5, 2, "오션뷰 스위트", 4, 20, 450000),
        ]

    def test_초기_잔여는_전부_총량과_같다(self, engine):
        # "판매 시작 전" 상태. 일부러 줄여둔 날짜는 하나도 없다 (1.9절 (4))
        mismatch = _scalar(
            engine,
            "SELECT COUNT(*) FROM room_daily_inventory WHERE remaining != total_quantity",
        )
        assert mismatch == 0

    def test_예약_테이블은_비어_있다(self, engine):
        # 시드는 재고까지다. 예약이 들어 있으면 시드가 아니라 오염이다
        assert _scalar(engine, "SELECT COUNT(*) FROM reservation") == 0
