"""reservation 컨텍스트의 도메인 모델 (스펙 1.6절).

이 파일은 T3(스키마)에서 테이블 정의로 시작한다. 애그리거트 메서드·VO는
2회차(T8~T10)에서 얹는다 — 테이블 정의가 먼저 있어야 CHECK 제약 검증(T30~T37)과
autogenerate 대조(T28)가 성립하기 때문이다.

`status`·`from_status`·`event`·`to_status`는 VARCHAR다. MySQL ENUM은 값을
추가하려면 테이블을 바꿔야 하고 순서 함정이 있다 — 상태 목록의 진실은 코드의
전이 표이고 DB는 문자열로 보관한다 (1.6절).
"""

from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlmodel import Field, SQLModel

from app.common.errors import InvalidRequestError
from app.inventory.domain.models import RoomType
from app.reservation.domain.enums import ReservationStatus
from app.reservation.domain.errors import InvalidStateTransitionError


class StayPeriod(BaseModel):
    """투숙 기간. **체크아웃 당일은 점유하지 않는다** — 하루를 더하면
    백투백 예약(앞 손님 체크아웃일 = 뒷 손님 체크인일)이 서로를 밀어낸다."""

    model_config = ConfigDict(frozen=True)

    check_in: date
    check_out: date

    def model_post_init(self, _context: Any) -> None:
        if self.check_out <= self.check_in:
            raise InvalidRequestError("체크아웃은 체크인보다 늦어야 합니다")
        # 박수 상한은 두지 않는다 (D29 뒤집음, 관리자 8/16). 예약 가능한 기간은
        # 재고를 열어둔 날짜 범위가 정한다 — 행이 없는 날짜는 차감 0행 → 409

    def occupied_dates(self) -> list[date]:
        """재고를 쓰는 날짜들. 차감·복원·락 키가 전부 이 목록에서 나온다."""
        return [
            self.check_in + timedelta(days=offset) for offset in range(self.nights())
        ]

    def nights(self) -> int:
        return (self.check_out - self.check_in).days


class GuestCount(BaseModel):
    """투숙 인원. 정원 검증(`guest_count <= capacity * room_count`)의 입력이다."""

    model_config = ConfigDict(frozen=True)

    value: int

    def model_post_init(self, _context: Any) -> None:
        if self.value < 1:
            raise InvalidRequestError("인원은 1명 이상이어야 합니다")


class Reservation(SQLModel, table=True):
    """예약 애그리거트 루트.

    `status`가 상태 전이 조건부 UPDATE의 `WHERE status = :expected` 대상이다 —
    동시성 승패가 이 컬럼에서 갈린다. `UNIQUE(user_id, idempotency_key)`가
    멱등성의 최후 방어선이다 — Redis가 죽어도 같은 키로 두 건이 저장되지 않는다.
    """

    __tablename__ = "reservation"
    __table_args__ = (
        UniqueConstraint("confirmation_code", name="uk_reservation_code"),
        UniqueConstraint("user_id", "idempotency_key", name="uk_reservation_idempotency"),
        # 만료 스케줄러의 WHERE status = 'PENDING' AND expires_at <= ? 경로
        Index("idx_reservation_expire", "status", "expires_at"),
        # FK가 요구하는 인덱스를 MySQL의 암묵 생성에 맡기지 않고 이름 붙여 명시한다.
        # 암묵 인덱스는 이름이 예측 불가라 모델-스키마 대조(T28)를 깨뜨린다
        Index("idx_reservation_room_type", "room_type_id"),
        CheckConstraint("check_out > check_in", name="ck_reservation_period"),
        CheckConstraint("room_count >= 1", name="ck_reservation_room_count"),
        CheckConstraint("guest_count >= 1", name="ck_reservation_guest_count"),
        CheckConstraint("price_per_night >= 0", name="ck_reservation_price_per_night"),
        CheckConstraint("total_price >= 0", name="ck_reservation_total_price"),
    )

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        idempotency_key: str,
        room_type: "RoomType",
        period: StayPeriod,
        room_count: int,
        guest_count: "GuestCount",
        price_per_night: "Money",
        confirmation_code: str,
        today: date,
        now: datetime,
        hold_minutes: int,
    ) -> "Reservation":
        """예약 생성 — 불변식 검증과 파생값 계산이 전부 여기 있다.

        `RoomType`을 통째로 받는다 — `(room_type_id, capacity)`로 분해해 받으면
        호출자가 둘을 어긋나게 조합할 수 있다 (파라미터는 가급적 도메인 객체로,
        관리자 지침). 저장은 규칙대로 ID만 한다 — 참조를 들고 있지 않는다.

        시각(`today`·`now`)은 유스케이스가 시계에서 한 번 읽어 넘긴다.
        도메인은 현재 시각을 직접 읽지 않는다 (D2, T26).
        """
        capacity = room_type.capacity
        # D21: checkOut > today다. checkIn >= today가 아니다 — 체크인일이
        # 지났어도 체크아웃일이 남았으면 진행 중인 투숙이라 허용한다
        if period.check_out <= today:
            raise InvalidRequestError("이미 끝난 숙박 기간입니다")
        if room_count < 1:
            raise InvalidRequestError("객실 수는 1 이상이어야 합니다")
        # D1: 정원 검증. capacity × room_count가 수용 한계다
        if guest_count.value > capacity * room_count:
            raise InvalidRequestError(
                f"인원 {guest_count.value}명이 정원({capacity}명 × {room_count}실)을 넘습니다"
            )

        # 총액 = 단가 × 박수 × 객실 수. 애그리거트 자신의 데이터만 쓰는 규칙이라
        # 서비스가 아니다 (2회차 리뷰) — 역산하지 않고 저장한다 (1.6절)
        total_price = price_per_night.multiply(period.nights()).multiply(room_count)
        return cls(
            confirmation_code=confirmation_code,
            user_id=user_id,
            room_type_id=room_type.id,  # 저장은 ID만 — 애그리거트 간 참조 금지
            check_in=period.check_in,
            check_out=period.check_out,
            room_count=room_count,
            guest_count=guest_count.value,
            price_per_night=price_per_night.amount,
            total_price=total_price.amount,
            # 항상 .value로 넣는다 — 순수 str이라 드라이버 문자열화 함정이 없고,
            # 상태 이름 리팩터링 때 grep에 걸린다
            status=ReservationStatus.PENDING.value,
            idempotency_key=idempotency_key,
            expires_at=now + timedelta(minutes=hold_minutes),
            created_at=now,
            updated_at=now,
        )

    def assert_confirmable(self, now: datetime) -> None:
        """확정 시간창 — `now < expiresAt` (스펙 1.4절 조건 열).

        스케줄러(30초 주기)가 아직 안 돌았을 뿐 이미 만료된 예약의 확정을
        막는다. 체크인 시간창과 같은 성격의 규칙이라 같은 자리(도메인)에 있다.
        """
        if now >= self.expires_at:
            raise InvalidStateTransitionError(
                f"만료 대기 중인 예약입니다 (만료 시각 {self.expires_at}, 현재 {now})"
            )

    def assert_check_in_window(self, today: date) -> None:
        """체크인 시간창 — `checkIn <= today < checkOut`.

        상한(`today < checkOut`)은 D4 기각으로 노쇼 스케줄러가 없는 지금,
        기간 지난 예약의 체크인을 막는 **유일한 장치**다 (T20).
        """
        if not (self.check_in <= today < self.check_out):
            raise InvalidStateTransitionError(
                f"체크인 가능 기간이 아닙니다 (투숙 {self.check_in}~{self.check_out}, "
                f"오늘 {today})"
            )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    confirmation_code: str = Field(sa_column=Column(String(32), nullable=False))
    user_id: str = Field(sa_column=Column(String(64), nullable=False))
    room_type_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("room_type.id", name="fk_reservation_room_type"),
            nullable=False,
        )
    )
    check_in: date = Field(sa_column=Column(Date, nullable=False))
    check_out: date = Field(sa_column=Column(Date, nullable=False))
    room_count: int = Field(sa_column=Column(Integer, nullable=False))
    guest_count: int = Field(sa_column=Column(Integer, nullable=False))
    price_per_night: int = Field(sa_column=Column(BigInteger, nullable=False))
    total_price: int = Field(sa_column=Column(BigInteger, nullable=False))
    status: str = Field(sa_column=Column(String(20), nullable=False))
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DATETIME(fsp=6), nullable=True)
    )
    terminated_at: datetime | None = Field(
        default=None, sa_column=Column(DATETIME(fsp=6), nullable=True)
    )
    created_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))


class ReservationStatusHistory(SQLModel, table=True):
    """상태 전이 이력 — 추가만 하고 수정·삭제하지 않는다.

    성공한 전이만 기록한다 (D19). 그래서 이 테이블은 실제로 일어난 전이와
    정확히 1:1이고, "복원이 몇 번 일어났는가"를 줄 수로 셀 수 있다.
    순서 판단은 `id`다 — `occurred_at`은 같은 트랜잭션이면 값이 같을 수 있다.
    """

    __tablename__ = "reservation_status_history"
    __table_args__ = (
        # 예약 하나의 이력을 순서대로 읽는 유일한 조회 경로.
        # reservation_id로 시작하므로 FK 인덱스 요건도 이것이 채운다
        Index("idx_history_reservation", "reservation_id", "id"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    reservation_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("reservation.id", name="fk_history_reservation"),
            nullable=False,
        )
    )
    from_status: str = Field(sa_column=Column(String(20), nullable=False))
    event: str = Field(sa_column=Column(String(20), nullable=False))
    to_status: str = Field(sa_column=Column(String(20), nullable=False))
    occurred_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))
