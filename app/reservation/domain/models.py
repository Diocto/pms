"""reservation 컨텍스트의 도메인 모델 (스펙 1.6절).

이 파일은 T3(스키마)에서 테이블 정의로 시작한다. 애그리거트 메서드·VO는
2회차(T8~T10)에서 얹는다 — 테이블 정의가 먼저 있어야 CHECK 제약 검증(T30~T37)과
autogenerate 대조(T28)가 성립하기 때문이다.

`status`·`from_status`·`event`·`to_status`는 VARCHAR다. MySQL ENUM은 값을
추가하려면 테이블을 바꿔야 하고 순서 함정이 있다 — 상태 목록의 진실은 코드의
전이 표이고 DB는 문자열로 보관한다 (1.6절).
"""

from datetime import date, datetime

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
