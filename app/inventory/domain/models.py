"""inventory 컨텍스트의 도메인 모델 (스펙 1.6절).

도메인 모델과 테이블 클래스를 통합한다 (clean-architecture.md). 대신 이 모듈은
`sqlmodel`·`sqlalchemy`·표준 라이브러리 외에 아무것도 import하지 않는다 (D27).

타입·이름을 전부 명시한다 — `__tablename__`, 컬럼 타입, 제약 이름까지.
자동 생성 규칙에 기대면 마이그레이션과 어긋나고, 그 어긋남을 T28이 잡는다.
스키마의 진실은 마이그레이션이다.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlmodel import Field, SQLModel

from app.common.errors import InvalidRequestError


class Money(BaseModel):
    """원 단위 정수 금액. 음수가 없고, 연산은 새 값을 돌려준다 (불변)."""

    model_config = ConfigDict(frozen=True)

    amount: int

    def model_post_init(self, _context: Any) -> None:
        # 불변식은 validator가 아니라 생성 시점의 도메인 검증이다 (D27)
        if self.amount < 0:
            raise InvalidRequestError("금액은 음수가 될 수 없습니다")

    def multiply(self, factor: int) -> "Money":
        return Money(amount=self.amount * factor)

    def add(self, other: "Money") -> "Money":
        return Money(amount=self.amount + other.amount)


class Hotel(SQLModel, table=True):
    """호텔. 시드 2곳 고정, 표시용 정보만 갖는다."""

    __tablename__ = "hotel"
    __table_args__ = (UniqueConstraint("name", name="uk_hotel_name"),)

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    name: str = Field(sa_column=Column(String(100), nullable=False))
    address: str = Field(sa_column=Column(String(255), nullable=False))
    created_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))


class RoomType(SQLModel, table=True):
    """객실타입. `capacity`가 인원 검증의 기준, `base_price`가 단가 스냅샷의 출처다."""

    __tablename__ = "room_type"
    __table_args__ = (
        UniqueConstraint("hotel_id", "name", name="uk_room_type_hotel_name"),
        CheckConstraint("capacity >= 1", name="ck_room_type_capacity"),
        CheckConstraint("total_quantity >= 0", name="ck_room_type_total_quantity"),
        CheckConstraint("base_price >= 0", name="ck_room_type_base_price"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    hotel_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("hotel.id", name="fk_room_type_hotel"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(String(100), nullable=False))
    capacity: int = Field(sa_column=Column(Integer, nullable=False))
    total_quantity: int = Field(sa_column=Column(Integer, nullable=False))
    base_price: int = Field(sa_column=Column(BigInteger, nullable=False))
    created_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))


class RoomDailyInventory(SQLModel, table=True):
    """일별 재고 — **동시성 제어의 대상 테이블.**

    이 테이블만 대리키 없이 자연키 `(room_type_id, stay_date)`를 PK로 쓴다 (D16).
    차감·복원 조건부 UPDATE가 이 클러스터드 인덱스로 정확히 한 행에 도달하고,
    잠기는 인덱스 레코드가 하나뿐이다.

    `remaining`의 CHECK 상·하한이 3층 방어의 최후선이다 — 하한이 초과 판매를,
    상한이 이중 복원을 막는다. 상한이 없으면 이중 복원은 아무 신호 없이 성공한다.
    """

    __tablename__ = "room_daily_inventory"
    __table_args__ = (
        CheckConstraint("total_quantity >= 0", name="ck_inventory_total_quantity"),
        CheckConstraint("remaining >= 0", name="ck_inventory_remaining_lower"),
        CheckConstraint(
            "remaining <= total_quantity", name="ck_inventory_remaining_upper"
        ),
    )

    room_type_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("room_type.id", name="fk_inventory_room_type"),
            primary_key=True,
        )
    )
    stay_date: date = Field(sa_column=Column(Date, primary_key=True))
    total_quantity: int = Field(sa_column=Column(Integer, nullable=False))
    remaining: int = Field(sa_column=Column(Integer, nullable=False))
    created_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))
    updated_at: datetime = Field(sa_column=Column(DATETIME(fsp=6), nullable=False))
