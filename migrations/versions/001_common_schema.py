"""공통 스키마 — hotel, room_type (스펙 1.6절)

리비전 ID: 001_common_schema
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "001_common_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hotel",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.UniqueConstraint("name", name="uk_hotel_name"),
    )
    op.create_table(
        "room_type",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("hotel_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("base_price", sa.BigInteger(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotel.id"], name="fk_room_type_hotel"),
        sa.UniqueConstraint("hotel_id", "name", name="uk_room_type_hotel_name"),
        sa.CheckConstraint("capacity >= 1", name="ck_room_type_capacity"),
        sa.CheckConstraint("total_quantity >= 0", name="ck_room_type_total_quantity"),
        sa.CheckConstraint("base_price >= 0", name="ck_room_type_base_price"),
    )


def downgrade() -> None:
    op.drop_table("room_type")
    op.drop_table("hotel")
