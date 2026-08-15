"""상태 전이 이력 — reservation_status_history (스펙 1.6절, D19)

추가만 하고 수정·삭제하지 않는다. 성공한 전이만 기록하므로 실제 전이와
정확히 1:1이고, "복원이 몇 번 일어났는가"를 줄 수로 셀 수 있다.

`idx_history_reservation(reservation_id, id)`가 이력을 순서대로 읽는 유일한
조회 경로이고, reservation_id로 시작하므로 FK 인덱스 요건도 함께 채운다.

리비전 ID: 004_reservation_history_schema
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "004_reservation_history_schema"
down_revision = "003_reservation_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservation_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("event", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("occurred_at", DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservation.id"], name="fk_history_reservation"
        ),
    )
    op.create_index(
        "idx_history_reservation",
        "reservation_status_history",
        ["reservation_id", "id"],
    )


def downgrade() -> None:
    op.drop_table("reservation_status_history")
