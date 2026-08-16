"""DB 제약 검증 — 도메인을 우회해 네이티브 SQL로 직접 위반을 시도한다.

테스트 T30~T37 (스펙 1.7절, D3). **VO 생성자에서 막히면 CHECK가 살아 있는지
알 수 없다.** 3층 방어의 최후선이 실제로 존재하는지는 SQL이 직접 거부당하는
것으로만 증명되므로, 이 파일만은 의도적으로 도메인을 건너뛴다.

각 제약이 뚫렸을 때 벌어지는 일이 다르다 — 표는 스펙 1.7절에 있다.
가장 조용한 것이 `remaining <= total_quantity`(T31)다. 이중 복원은
성공한 것처럼 보이고 팔 수 있는 방이 늘어나는데 아무 신호가 없다.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

# MySQL: CHECK 위반은 OperationalError(3819), UK/PK 위반은 IntegrityError(1062)
CONSTRAINT_ERRORS = (IntegrityError, OperationalError)

# CHECK 위반(3819)·중복 키(1062)만 통과다. 락 타임아웃(1205) 같은 무관한
# OperationalError까지 통과시키면 "제약이 거부했다"는 판정이 흐려진다 (리뷰 지적)
_ALLOWED_ERRNO = {3819, 1062}


def _assert_constraint_rejection(excinfo) -> None:
    errno = getattr(excinfo.value.orig, "args", [None])[0]
    assert errno in _ALLOWED_ERRNO, f"제약 위반이 아닌 오류다: errno={errno}"


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def clean_reservation(engine):
    yield
    with engine.begin() as conn:
        # 자기 데이터만 지운다 — 병렬 실행 시 남의 검증 데이터를 지우면 안 된다
        conn.execute(
            text(
                "DELETE FROM reservation_status_history WHERE reservation_id IN"
                " (SELECT id FROM reservation WHERE user_id LIKE 'test-constraint-%')"
            )
        )
        conn.execute(
            text("DELETE FROM reservation WHERE user_id LIKE 'test-constraint-%'")
        )


RESERVATION_INSERT = text(
    """
    INSERT INTO reservation
      (confirmation_code, user_id, room_type_id, check_in, check_out,
       room_count, guest_count, price_per_night, total_price, status,
       idempotency_key, expires_at, created_at, updated_at)
    VALUES
      (:code, :user_id, 1, :check_in, :check_out,
       :room_count, :guest_count, 150000, 450000, 'PENDING',
       :idempotency_key, NOW(6), NOW(6), NOW(6))
    """
)


def _reservation_row(**overrides) -> dict:
    row = {
        "code": "TEST-OK-0001",
        "user_id": "test-constraint-01",
        "check_in": "2026-09-01",
        "check_out": "2026-09-04",
        "room_count": 1,
        "guest_count": 2,
        "idempotency_key": "idem-0001",
    }
    row.update(overrides)
    return row


def test_T30_remaining은_음수가_될_수_없다(engine):
    """DB 제약(3층 방어) — remaining을 음수로 만드는 UPDATE를 CHECK가 거부한다.
    조건부 UPDATE의 `remaining >= :count`가 뚫려도 초과 판매된 데이터가 저장될
    수 없다는 최후선의 증명이다."""
    with pytest.raises(CONSTRAINT_ERRORS) as excinfo, engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = -1"
                " WHERE room_type_id = 1 AND stay_date = '2026-09-01'"
            )
        )
    _assert_constraint_rejection(excinfo)


def test_T31_remaining은_총량을_넘을_수_없다_이중_복원_방어선(engine):
    """DB 제약(3층 방어) — remaining이 total_quantity를 넘는 UPDATE를 CHECK가
    거부한다. 이중 복원은 성공한 것처럼 보이고 팔 수 있는 방이 늘어나는데 아무
    신호가 없는 가장 조용한 사고라, 이 제약이 마지막에 막는다."""
    with pytest.raises(CONSTRAINT_ERRORS) as excinfo, engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = total_quantity + 1"
                " WHERE room_type_id = 1 AND stay_date = '2026-09-01'"
            )
        )
    _assert_constraint_rejection(excinfo)


@pytest.mark.parametrize("bad_count", [0, -5])
def test_T32_객실_수는_1_이상이다(engine, clean_reservation, bad_count):
    """DB 제약(3층 방어) — room_count가 0·음수인 예약 INSERT를 CHECK가 거부한다."""
    # -5가 통과하면 차감 UPDATE의 remaining >= :count를 지나며 재고가 늘어난다
    with pytest.raises(CONSTRAINT_ERRORS) as excinfo, engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row(room_count=bad_count))
    _assert_constraint_rejection(excinfo)


def test_T33_뒤집힌_기간은_저장될_수_없다(engine, clean_reservation):
    """DB 제약(3층 방어) — check_out이 check_in보다 앞선 예약 INSERT를 CHECK가
    거부한다."""
    # 점유 날짜 목록이 비어 재고를 하나도 안 깎는 예약을 막는다
    with pytest.raises(CONSTRAINT_ERRORS) as excinfo, engine.begin() as conn:
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(check_in="2026-09-04", check_out="2026-09-01"),
        )
    _assert_constraint_rejection(excinfo)


def test_T33b_같은_날짜도_기간이_아니다(engine, clean_reservation):
    """DB 제약(3층 방어) — check_in과 check_out이 같은 0박 예약도 INSERT가
    거부된다. 부등호의 경계(등호)까지 막히는지 T33과 별도로 확인한다."""
    with pytest.raises(CONSTRAINT_ERRORS) as excinfo, engine.begin() as conn:
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(check_in="2026-09-01", check_out="2026-09-01"),
        )
    _assert_constraint_rejection(excinfo)


def test_T34_인원은_1_이상이다(engine, clean_reservation):
    """DB 제약(3층 방어) — guest_count가 0인 예약 INSERT를 CHECK가 거부한다."""
    with pytest.raises(CONSTRAINT_ERRORS) as excinfo, engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row(guest_count=0))
    _assert_constraint_rejection(excinfo)


def test_T35_같은_사용자의_같은_멱등_키는_두_번_저장될_수_없다(engine, clean_reservation):
    """DB 제약(3층 방어) — 같은 (user_id, idempotency_key) 조합의 두 번째
    INSERT를 유니크 제약이 거부한다. Redis 멱등 키가 죽어도 중복 예약이
    저장되지 않는 최종 방어선이다."""
    with engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row())
    with pytest.raises(IntegrityError) as excinfo, engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row(code="TEST-OK-0002"))
    _assert_constraint_rejection(excinfo)


def test_T35b_다른_사용자는_같은_키_문자열을_써도_간섭하지_않는다(engine, clean_reservation):
    """DB 제약(3층 방어) — 유니크 제약이 (user_id, idempotency_key) 조합이라
    다른 사용자는 같은 키 문자열로도 저장된다. 키가 사용자별로 격리된다는
    반대 방향의 확인이다."""
    # UK가 (user_id, idempotency_key) 조합이라는 것의 반대 방향 확인
    with engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row())
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(code="TEST-OK-0002", user_id="test-constraint-02"),
        )


def test_T36_확인번호는_중복될_수_없다(engine, clean_reservation):
    """DB 제약(3층 방어) — 같은 confirmation_code의 두 번째 INSERT를 유니크
    제약이 거부한다. 확인번호가 겹치면 남의 예약이 조회·취소될 수 있다."""
    with engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row())
    with pytest.raises(IntegrityError) as excinfo, engine.begin() as conn:
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(user_id="test-constraint-02", idempotency_key="idem-0002"),
        )
    _assert_constraint_rejection(excinfo)


def test_T37_같은_타입_날짜의_재고_행은_둘일_수_없다(engine):
    """DB 제약(3층 방어) — 같은 (room_type_id, stay_date) 재고 행의 INSERT를
    유니크 제약이 거부한다."""
    # 뚫리면 잔여 수량의 진실이 두 곳이 된다
    with pytest.raises(IntegrityError) as excinfo, engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO room_daily_inventory"
                " (room_type_id, stay_date, total_quantity, remaining,"
                "  created_at, updated_at)"
                " VALUES (1, '2026-09-01', 100, 100, NOW(6), NOW(6))"
            )
        )
    _assert_constraint_rejection(excinfo)
