"""시드 — 일별 재고 450행 (스펙 1.9절 (1)(4))

**고정 날짜** `2026-08-01` ~ `2026-10-29` 90일 × 객실타입 5종 = 450행.
`CURDATE()` 기준이면 마이그레이션 실행일에 따라 범위가 움직여서 세션마다
다른 "오늘"을 가정하게 된다 (D13). 고정이라 몇 번을 재시드해도 같은 상태다.

초기 `remaining`은 전부 `total_quantity`와 같다 — "판매 시작 전" 상태.
특정 날짜의 재고를 줄이고 싶으면 시드가 아니라 테스트가 직접 UPDATE한다.

리비전 ID: 052_seed_daily_inventory
"""

from alembic import op

revision = "052_seed_daily_inventory"
down_revision = "051_seed_hotel_room_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO room_daily_inventory
          (room_type_id, stay_date, total_quantity, remaining, created_at, updated_at)
        WITH RECURSIVE dates (stay_date) AS (
          SELECT CAST('2026-08-01' AS DATE)
          UNION ALL
          SELECT stay_date + INTERVAL 1 DAY
            FROM dates
           WHERE stay_date < CAST('2026-10-29' AS DATE)
        )
        SELECT rt.id, d.stay_date, rt.total_quantity, rt.total_quantity, NOW(6), NOW(6)
          FROM room_type rt
         CROSS JOIN dates d
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM room_daily_inventory
         WHERE stay_date BETWEEN '2026-08-01' AND '2026-10-29'
        """
    )
