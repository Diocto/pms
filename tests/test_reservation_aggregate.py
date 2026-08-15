"""예약 애그리거트 규칙 (테스트 T16~T26, 스펙 1.2절·2.2절·D1·D21).

인프라 없음. 시각은 전부 인자로 받는다 — 도메인 안에서 `datetime.now()`를
부르는 것은 금지이고 T26이 그것을 정적으로 확인한다.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from app.common.errors import InvalidRequestError
from app.inventory.domain.models import Money
from app.reservation.domain.enums import ReservationStatus
from app.reservation.domain.errors import InvalidStateTransitionError
from app.reservation.domain.models import GuestCount, Reservation, StayPeriod
from app.reservation.domain.services import generate_confirmation_code

TODAY = date(2026, 8, 15)
NOW = datetime(2026, 8, 15, 12, 0, 0)


def _create(**overrides) -> Reservation:
    arguments = {
        "user_id": "user-1",
        "idempotency_key": "idem-1",
        "room_type_id": 1,
        "capacity": 2,
        "period": StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        "room_count": 1,
        "guest_count": GuestCount(value=2),
        "price_per_night": Money(amount=150000),
        "confirmation_code": "260901-H1R1-TESTCODE",
        "today": TODAY,
        "now": NOW,
        "hold_minutes": 10,
    }
    arguments.update(overrides)
    return Reservation.create(**arguments)


def test_T16_정원을_넘는_인원은_거부된다():
    with pytest.raises(InvalidRequestError):
        _create(guest_count=GuestCount(value=3))  # 정원 2 × 1실 = 2


def test_T17_정원과_정확히_같으면_경계에서_허용된다():
    reservation = _create(guest_count=GuestCount(value=4), room_count=2)  # 2×2=4
    assert reservation.guest_count == 4


def test_T18_만료_시각은_now_더하기_보류_시간이다():
    reservation = _create()
    assert reservation.expires_at == datetime(2026, 8, 15, 12, 10, 0)


def test_생성_직후_상태는_PENDING이고_금액이_계산돼_있다():
    reservation = _create()
    assert reservation.status == ReservationStatus.PENDING.value
    assert reservation.price_per_night == 150000
    assert reservation.total_price == 450000  # 150000 × 3박 × 1실
    assert reservation.created_at == NOW and reservation.updated_at == NOW


class Test_체크인_시간창:  # T19~T21
    def _confirmed(self, check_in: date, check_out: date) -> Reservation:
        reservation = _create(
            period=StayPeriod(check_in=check_in, check_out=check_out),
            today=check_in,  # 생성 조건(D21)은 여기서 관심사가 아니라 항상 통과시킨다
        )
        # 전이 표 우회는 테스트 셋업 한정이다 — 프로덕션 쓰기 경로는
        # apply_event()가 표를 강제한다
        reservation.status = ReservationStatus.CONFIRMED.value
        return reservation

    def test_T19_도착_전이면_거부(self):
        reservation = self._confirmed(date(2026, 8, 16), date(2026, 8, 18))
        with pytest.raises(InvalidStateTransitionError):
            reservation.assert_check_in_window(TODAY)

    def test_T20_기간이_지나면_거부__상한이_있는지_확인(self):
        # D4 기각으로 노쇼 스케줄러가 없다. 이 상한이 기간 지난 예약의
        # 체크인을 막는 유일한 장치다
        reservation = self._confirmed(date(2026, 8, 10), date(2026, 8, 12))
        with pytest.raises(InvalidStateTransitionError):
            reservation.assert_check_in_window(TODAY)

    def test_T20b_체크아웃_당일도_거부(self):
        reservation = self._confirmed(date(2026, 8, 13), date(2026, 8, 15))
        with pytest.raises(InvalidStateTransitionError):
            reservation.assert_check_in_window(TODAY)

    def test_T21_기간_안이면_허용(self):
        for check_in in (date(2026, 8, 15), date(2026, 8, 14)):
            reservation = self._confirmed(check_in, date(2026, 8, 17))
            reservation.assert_check_in_window(TODAY)  # 예외 없음


class Test_확정_시간창:  # 스펙 1.4절 조건 열의 둘째 시간 조건 — now < expiresAt
    def test_만료_시각_전이면_허용(self):
        reservation = _create()  # expires_at = 12:10
        reservation.assert_confirmable(datetime(2026, 8, 15, 12, 9, 59))  # 예외 없음

    def test_만료_시각_이후면_거부(self):
        # 스케줄러(30초 주기)가 아직 안 돌았을 뿐 이미 만료된 예약이다.
        # 유스케이스가 이 검사를 빠뜨리면 만료됐어야 할 예약이 확정된다
        reservation = _create()
        with pytest.raises(InvalidStateTransitionError):
            reservation.assert_confirmable(datetime(2026, 8, 15, 12, 10, 0))  # 경계

    def test_거부_메시지에_만료_시각이_실린다(self):
        reservation = _create()
        with pytest.raises(InvalidStateTransitionError) as excinfo:
            reservation.assert_confirmable(datetime(2026, 8, 15, 13, 0, 0))
        assert "12:10" in str(excinfo.value)


class Test_생성_조건_D21:  # T23a~T23d — checkOut > today이지 checkIn >= today가 아니다
    def test_T23a_끝난_숙박은_거부(self):
        with pytest.raises(InvalidRequestError):
            _create(
                period=StayPeriod(check_in=date(2026, 8, 10), check_out=date(2026, 8, 12))
            )

    def test_T23b_오늘_끝나는_숙박도_거부__경계(self):
        with pytest.raises(InvalidRequestError):
            _create(
                period=StayPeriod(check_in=date(2026, 8, 13), check_out=date(2026, 8, 15))
            )

    def test_T23c_진행_중인_투숙은_허용__이게_D21의_요점이다(self):
        reservation = _create(
            period=StayPeriod(check_in=date(2026, 8, 14), check_out=date(2026, 8, 16))
        )
        assert reservation.check_in == date(2026, 8, 14)

    def test_T23d_시드_계약의_체크인_시연_경로가_살아_있다(self):
        # 1.9절: checkIn = 2026-08-15(오늘), checkOut = 2026-08-17
        reservation = _create(
            period=StayPeriod(check_in=date(2026, 8, 15), check_out=date(2026, 8, 17))
        )
        assert reservation.check_out == date(2026, 8, 17)


def test_T24_총액은_단가_곱하기_박수_곱하기_객실수다():
    reservation = _create(
        price_per_night=Money(amount=250000),
        period=StayPeriod(check_in=date(2026, 9, 1), check_out=date(2026, 9, 3)),
        room_count=2,
        guest_count=GuestCount(value=4),
    )
    assert reservation.total_price == 1000000  # 250000 × 2박 × 2실


def test_T25_확인번호_형식():
    code = generate_confirmation_code(
        check_in=date(2026, 9, 1), hotel_id=1, room_type_id=3
    )
    prefix, middle, random_part = code.split("-")
    assert prefix == "260901"
    assert middle == "H1R3"
    assert len(random_part) == 8
    # 혼동 문자(0·O·1·I)가 없다
    assert not (set(random_part) & set("0O1I"))


def test_T25a_같은_조건_1000건이_전부_다르다():
    codes = {
        generate_confirmation_code(check_in=date(2026, 9, 1), hotel_id=1, room_type_id=1)
        for _ in range(1000)
    }
    assert len(codes) == 1000


def test_T26_도메인은_현재_시각을_직접_읽지_않는다():
    """`datetime.now()`·`date.today()`가 domain 모듈에 없다 — 정적 확인.

    시계를 주입받지 않고 직접 읽으면 KST 고정(D2)이 조용히 우회된다.
    grep subprocess 판이 cwd에 따라 아무것도 검사하지 않고 통과했다
    (리뷰가 /tmp 실행으로 실증) — 절대 경로 + 모집단 확인으로 다시 쓴다.
    """
    project_root = Path(__file__).resolve().parent.parent
    domain_directories = [
        project_root / "app" / "inventory" / "domain",
        project_root / "app" / "reservation" / "domain",
    ]
    forbidden = ("datetime.now(", "date.today(", ".now()")
    scanned = 0
    violations: list[str] = []
    for directory in domain_directories:
        assert directory.is_dir(), f"도메인 디렉터리가 없다: {directory}"
        for source in sorted(directory.glob("*.py")):
            scanned += 1
            for line_number, line in enumerate(
                source.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if any(pattern in line for pattern in forbidden):
                    violations.append(f"{source.name}:{line_number}: {line.strip()}")
    assert scanned >= 6, f"검사한 파일이 {scanned}개뿐이다 — 순회가 깨졌다"
    assert violations == [], f"도메인이 시각을 직접 읽는다: {violations}"
