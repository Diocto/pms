"""일별 재고 — room_daily_inventory (스펙 1.6절, D16)

동시성 제어의 대상 테이블. 자연키 복합 PK `(room_type_id, stay_date)`가
클러스터드 인덱스라 조건부 UPDATE가 세컨더리 인덱스를 거치지 않고 행에
도달하고, 잠기는 인덱스 레코드가 하나뿐이다.

`remaining`의 CHECK 상·하한이 3층 방어의 최후선이다 — 하한이 초과 판매를,
상한이 이중 복원을 막는다.

리비전 ID: 002_inventory_schema
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "002_inventory_schema"
down_revision = "001_common_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "room_daily_inventory",
        sa.Column("room_type_id", sa.BigInteger(), primary_key=True),
        sa.Column("stay_date", sa.Date(), primary_key=True),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("remaining", sa.Integer(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["room_type_id"], ["room_type.id"], name="fk_inventory_room_type"
        ),
        sa.CheckConstraint("total_quantity >= 0", name="ck_inventory_total_quantity"),
        sa.CheckConstraint("remaining >= 0", name="ck_inventory_remaining_lower"),
        sa.CheckConstraint(
            "remaining <= total_quantity", name="ck_inventory_remaining_upper"
        ),
    )


def downgrade() -> None:
    op.drop_table("room_daily_inventory")
