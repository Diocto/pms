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


# 리비전 054의 지역 대역. (시작 id, 끝 id, 이름 접두, 주소 접두)
_REGION_BANDS: list[tuple[int, int, str, str]] = [
    (3, 23, "서울", "서울특별시 중구 세종대로"),
    (24, 36, "부산", "부산광역시 해운대구 해운대해변로"),
    (37, 52, "제주", "제주특별자치도 제주시 중앙로"),
    (53, 64, "강원", "강원특별자치도 속초시 중앙로"),
    (65, 72, "경기", "경기도 고양시 일산동구 중앙로"),
    (73, 78, "인천", "인천광역시 연수구 컨벤시아대로"),
    (79, 84, "경주", "경상북도 경주시 첨성로"),
    (85, 89, "전주", "전라북도 전주시 완산구 어진길"),
    (90, 95, "여수", "전라남도 여수시 돌산로"),
    (96, 100, "대구", "대구광역시 중구 동성로"),
]


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
    """스펙 1.9절의 숫자 그대로. F03·F04·F05가 이 값을 상수로 박는다.

    2026-08-16 확장(리비전 053): 호텔 3~100이 추가됐다. 호텔 1·2와
    객실타입 1~5의 기존 계약은 **한 글자도 바뀌지 않는다** — F04의
    부하테스트 시나리오가 그 값을 그대로 쓰기 때문이다.
    """

    def test_호텔_100곳(self, engine):
        assert _scalar(engine, "SELECT COUNT(*) FROM hotel") == 100

    def test_객실타입_299종(self, engine):
        # 기존 5종 + 확장 98곳 × 3종
        assert _scalar(engine, "SELECT COUNT(*) FROM room_type") == 299

    def test_재고_26910행(self, engine):
        # 299종 × 90일
        assert _scalar(engine, "SELECT COUNT(*) FROM room_daily_inventory") == 26910

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

    def test_기존_호텔_계약_전체를_고정한다(self, engine):
        # id 한 칸만 보면 나머지 매핑이 무방비다 (리뷰 지적). 표를 통째로 박는다
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name FROM hotel WHERE id <= 2 ORDER BY id")
            ).all()
        assert rows == [(1, "서울 그랜드 호텔"), (2, "부산 오션뷰 호텔")]

    def test_기존_객실타입_계약_전체를_고정한다(self, engine):
        # 스펙 1.9절 (3) 표 그대로. capacity가 틀리면 F03의 정원
        # 검증 상수가 통합 시점에 조용히 어긋난다
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, hotel_id, name, capacity, total_quantity, base_price"
                    " FROM room_type WHERE id <= 5 ORDER BY id"
                )
            ).all()
        assert rows == [
            (1, 1, "스탠다드", 2, 100, 150000),
            (2, 1, "디럭스", 3, 50, 250000),
            (3, 1, "스위트", 4, 10, 600000),
            (4, 2, "오션뷰 스탠다드", 2, 80, 180000),
            (5, 2, "오션뷰 스위트", 4, 20, 450000),
        ]

    def test_확장_호텔은_이름과_주소가_id에서_유도된다(self, engine):
        # 규칙(리비전 054): 호텔 h(3~100)의 이름과 주소는 h가 속한 지역 대역에서
        # 유도된다. 규칙에서 벗어난 행이 하나라도 있으면 F05의 상수 생성이
        # 조용히 어긋난다.
        #
        # 대역 값을 마이그레이션에서 읽어오지 않고 여기 따로 적는다 —
        # 읽어오면 마이그레이션이 잘못돼도 테스트가 같이 잘못된다.
        for lo, hi, name_prefix, address_prefix in _REGION_BANDS:
            mismatch = _scalar(
                engine,
                f"SELECT COUNT(*) FROM hotel WHERE id BETWEEN {lo} AND {hi}"
                f" AND (name != CONCAT('{name_prefix} 호텔 ', LPAD(id, 3, '0'))"
                f"   OR address != CONCAT('{address_prefix} ', id))",
            )
            assert mismatch == 0, f"{name_prefix} 대역({lo}~{hi})에 규칙 밖 행이 있다"

    def test_지역_분포가_기획한_곳수와_일치한다(self, engine):
        # 대역을 옮기면 곳수가 조용히 바뀐다. 곳수를 따로 박아 그걸 잡는다.
        # 합계 98곳(3~100) + 호텔 1·2 = 100곳.
        expected = {
            "서울": 21, "부산": 13, "제주": 16, "강원": 12, "경기": 8,
            "인천": 6, "경주": 6, "전주": 5, "여수": 6, "대구": 5,
        }
        assert sum(expected.values()) == 98
        for lo, hi, name_prefix, _ in _REGION_BANDS:
            count = _scalar(
                engine,
                f"SELECT COUNT(*) FROM hotel WHERE id BETWEEN {lo} AND {hi}",
            )
            assert count == expected[name_prefix], f"{name_prefix} 곳수가 바뀌었다"

    def test_호텔_1과_2의_주소는_건드리지_않았다(self, engine):
        # 리비전 051이 넣은 값이다. 054는 3~100만 손대야 한다.
        assert (
            _scalar(engine, "SELECT address FROM hotel WHERE id = 1")
            == "서울특별시 중구 을지로 100"
        )
        assert (
            _scalar(engine, "SELECT address FROM hotel WHERE id = 2")
            == "부산광역시 해운대구 해운대해변로 200"
        )

    def test_확장_객실타입_id는_호텔id_곱_1000_더하기_1_2_3이다(self, engine):
        # 규칙 밖 id가 0개이고, 규칙이 만드는 id가 전부 있다 — 양방향으로 본다
        out_of_rule = _scalar(
            engine,
            "SELECT COUNT(*) FROM room_type WHERE hotel_id BETWEEN 3 AND 100"
            " AND id NOT IN (hotel_id * 1000 + 1, hotel_id * 1000 + 2, hotel_id * 1000 + 3)",
        )
        assert out_of_rule == 0
        assert (
            _scalar(
                engine,
                "SELECT COUNT(*) FROM room_type WHERE hotel_id BETWEEN 3 AND 100",
            )
            == 98 * 3
        )

    def test_확장_객실타입의_구성은_전_호텔이_같다(self, engine):
        # (이름, 정원, 총량, 단가)의 서로 다른 조합이 정확히 3가지뿐이어야
        # "전 호텔 동일 구성"이 증명된다
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT id - hotel_id * 1000 AS n, name, capacity,"
                    " total_quantity, base_price"
                    " FROM room_type WHERE hotel_id BETWEEN 3 AND 100 ORDER BY n"
                )
            ).all()
        assert rows == [
            (1, "스탠다드", 2, 50, 150000),
            (2, "디럭스", 3, 30, 250000),
            (3, "스위트", 4, 10, 400000),
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
