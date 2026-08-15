"""예약 — reservation (스펙 1.6절)

`UNIQUE(user_id, idempotency_key)`가 멱등성의 최후 방어선이다 — Redis가
죽어도 같은 키로 두 건이 저장되지 않는다 (D9).

`idx_reservation_room_type`은 FK가 요구하는 인덱스를 MySQL의 암묵 생성에
맡기지 않고 이름 붙인 것이다. 암묵 인덱스는 이름이 예측 불가라
모델-스키마 대조(T28)를 깨뜨린다.

리비전 ID: 003_reservation_schema
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "003_reservation_schema"
down_revision = "002_inventory_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservation",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("confirmation_code", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("room_type_id", sa.BigInteger(), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("room_count", sa.Integer(), nullable=False),
        sa.Column("guest_count", sa.Integer(), nullable=False),
        sa.Column("price_per_night", sa.BigInteger(), nullable=False),
        sa.Column("total_price", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("expires_at", DATETIME(fsp=6), nullable=False),
        sa.Column("confirmed_at", DATETIME(fsp=6), nullable=True),
        sa.Column("terminated_at", DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["room_type_id"], ["room_type.id"], name="fk_reservation_room_type"
        ),
        sa.UniqueConstraint("confirmation_code", name="uk_reservation_code"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uk_reservation_idempotency"
        ),
        sa.CheckConstraint("check_out > check_in", name="ck_reservation_period"),
        sa.CheckConstraint("room_count >= 1", name="ck_reservation_room_count"),
        sa.CheckConstraint("guest_count >= 1", name="ck_reservation_guest_count"),
        sa.CheckConstraint(
            "price_per_night >= 0", name="ck_reservation_price_per_night"
        ),
        sa.CheckConstraint("total_price >= 0", name="ck_reservation_total_price"),
    )
    # 만료 스케줄러의 WHERE status = 'PENDING' AND expires_at <= ? 경로
    op.create_index("idx_reservation_expire", "reservation", ["status", "expires_at"])
    op.create_index("idx_reservation_room_type", "reservation", ["room_type_id"])


def downgrade() -> None:
    op.drop_table("reservation")
