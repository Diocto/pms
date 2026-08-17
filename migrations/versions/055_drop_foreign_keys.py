"""외래키 제약 4개를 제거한다 (ADR-0066, 관리자 지시 2026-08-17).

참조는 id 값으로만 기록한다. 존재 검증은 애플리케이션이 한다 — 예약 생성이
객실타입을 먼저 조회해 없으면 404를 내므로, 이 제약이 실제로 막던 경로는
운영 API에 없다. 초과 판매를 막는 제약(CHECK·UNIQUE)은 그대로 남는다.

MySQL은 외래키를 만들 때 같은 이름의 인덱스를 함께 만든다. **인덱스는
지우지 않는다** — 자식 → 부모 조회가 그 인덱스를 탄다.
"""

from alembic import op

revision = "055_drop_foreign_keys"
down_revision = "054_seed_hotel_addresses"
branch_labels = None
depends_on = None

# (제약 이름, 테이블) — 003·004·001·002에서 만든 순서의 역순
_FOREIGN_KEYS = [
    ("fk_history_reservation", "reservation_status_history"),
    ("fk_reservation_room_type", "reservation"),
    ("fk_inventory_room_type", "room_daily_inventory"),
    ("fk_room_type_hotel", "room_type"),
]


def upgrade() -> None:
    for name, table in _FOREIGN_KEYS:
        op.drop_constraint(name, table, type_="foreignkey")


def downgrade() -> None:
    # 되돌릴 때는 부모부터 — 자식 제약이 부모 행의 존재를 전제한다
    op.create_foreign_key(
        "fk_room_type_hotel", "room_type", "hotel", ["hotel_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_inventory_room_type",
        "room_daily_inventory", "room_type", ["room_type_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_reservation_room_type",
        "reservation", "room_type", ["room_type_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_history_reservation",
        "reservation_status_history", "reservation", ["reservation_id"], ["id"],
    )
