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

# MySQL: CHECK 위반은 OperationalError(3819), UK/PK/FK 위반은 IntegrityError
CONSTRAINT_ERRORS = (IntegrityError, OperationalError)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def clean_reservation(engine):
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reservation_status_history"))
        conn.execute(text("DELETE FROM reservation WHERE user_id LIKE 'test-%'"))


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
    with pytest.raises(CONSTRAINT_ERRORS), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = -1"
                " WHERE room_type_id = 1 AND stay_date = '2026-09-01'"
            )
        )


def test_T31_remaining은_총량을_넘을_수_없다_이중_복원_방어선(engine):
    with pytest.raises(CONSTRAINT_ERRORS), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE room_daily_inventory SET remaining = total_quantity + 1"
                " WHERE room_type_id = 1 AND stay_date = '2026-09-01'"
            )
        )


@pytest.mark.parametrize("bad_count", [0, -5])
def test_T32_객실_수는_1_이상이다(engine, clean_reservation, bad_count):
    # -5가 통과하면 차감 UPDATE의 remaining >= :count를 지나며 재고가 늘어난다
    with pytest.raises(CONSTRAINT_ERRORS), engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row(room_count=bad_count))


def test_T33_뒤집힌_기간은_저장될_수_없다(engine, clean_reservation):
    # 점유 날짜 목록이 비어 재고를 하나도 안 깎는 예약을 막는다
    with pytest.raises(CONSTRAINT_ERRORS), engine.begin() as conn:
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(check_in="2026-09-04", check_out="2026-09-01"),
        )


def test_T33b_같은_날짜도_기간이_아니다(engine, clean_reservation):
    with pytest.raises(CONSTRAINT_ERRORS), engine.begin() as conn:
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(check_in="2026-09-01", check_out="2026-09-01"),
        )


def test_T34_인원은_1_이상이다(engine, clean_reservation):
    with pytest.raises(CONSTRAINT_ERRORS), engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row(guest_count=0))


def test_T35_같은_사용자의_같은_멱등_키는_두_번_저장될_수_없다(engine, clean_reservation):
    with engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row())
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row(code="TEST-OK-0002"))


def test_T35b_다른_사용자는_같은_키_문자열을_써도_간섭하지_않는다(engine, clean_reservation):
    # UK가 (user_id, idempotency_key) 조합이라는 것의 반대 방향 확인
    with engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row())
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(code="TEST-OK-0002", user_id="test-constraint-02"),
        )


def test_T36_확인번호는_중복될_수_없다(engine, clean_reservation):
    with engine.begin() as conn:
        conn.execute(RESERVATION_INSERT, _reservation_row())
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            RESERVATION_INSERT,
            _reservation_row(user_id="test-constraint-02", idempotency_key="idem-0002"),
        )


def test_T37_같은_타입_날짜의_재고_행은_둘일_수_없다(engine):
    # 뚫리면 잔여 수량의 진실이 두 곳이 된다
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO room_daily_inventory"
                " (room_type_id, stay_date, total_quantity, remaining,"
                "  created_at, updated_at)"
                " VALUES (1, '2026-09-01', 100, 100, NOW(6), NOW(6))"
            )
        )
