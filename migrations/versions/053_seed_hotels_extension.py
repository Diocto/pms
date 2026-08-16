"""시드 확장 — 호텔 3~100, 객실타입 294종, 재고 26,460행 (스펙 1.9절, 관리자 지시 2026-08-16)

F05의 검색 화면이 "호텔 N곳 조회" 구조라 호텔이 100곳 필요하다.
**호텔 1·2와 객실타입 1~5의 기존 계약(리비전 051·052)은 건드리지 않는다** —
F04의 부하테스트 시나리오와 기존 테스트가 그 값을 그대로 쓴다.

확장 규칙 — F05가 이 규칙만으로 매핑 상수를 생성할 수 있어야 한다:
- 호텔 h (3 ≤ h ≤ 100): 이름 '호텔 003' … '호텔 100' (3자리 0채움),
  주소 '서울특별시 테스트구 예약로 h'
- 객실타입 id = h × 1000 + n (n = 1, 2, 3). 전 호텔 동일 구성:
  | n | 이름 | capacity | total_quantity | base_price |
  |---|---|---|---|---|
  | 1 | 스탠다드 | 2 | 50 | 150000 |
  | 2 | 디럭스 | 3 | 30 | 250000 |
  | 3 | 스위트 | 4 | 10 | 400000 |
- 재고: 기존과 같은 고정 날짜 2026-08-01 ~ 2026-10-29 (90일, D13),
  초기 remaining = total_quantity

id 대역이 테스트 전용 대역(900~999, 9300번대, 93200번대)과 겹치지 않는다 —
확장 객실타입 id는 3001~3003, 4001~4003, …, 100001~100003이다.

리비전 ID: 053_seed_hotels_extension
"""

from alembic import op

revision = "053_seed_hotels_extension"
down_revision = "052_seed_daily_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO hotel (id, name, address, created_at)
        WITH RECURSIVE hotels (i) AS (
          SELECT 3 UNION ALL SELECT i + 1 FROM hotels WHERE i < 100
        )
        SELECT i,
               CONCAT('호텔 ', LPAD(i, 3, '0')),
               CONCAT('서울특별시 테스트구 예약로 ', i),
               NOW(6)
          FROM hotels
        """
    )
    op.execute(
        """
        INSERT INTO room_type
          (id, hotel_id, name, capacity, total_quantity, base_price, created_at)
        WITH RECURSIVE hotels (i) AS (
          SELECT 3 UNION ALL SELECT i + 1 FROM hotels WHERE i < 100
        )
        SELECT i * 1000 + t.n, i, t.name, t.capacity, t.quantity, t.price, NOW(6)
          FROM hotels
         CROSS JOIN (
               SELECT 1 AS n, '스탠다드' AS name, 2 AS capacity,
                      50 AS quantity, 150000 AS price
               UNION ALL SELECT 2, '디럭스', 3, 30, 250000
               UNION ALL SELECT 3, '스위트', 4, 10, 400000
         ) t
        """
    )
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
         WHERE rt.hotel_id BETWEEN 3 AND 100
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE i FROM room_daily_inventory i
          JOIN room_type rt ON rt.id = i.room_type_id
         WHERE rt.hotel_id BETWEEN 3 AND 100
        """
    )
    op.execute("DELETE FROM room_type WHERE hotel_id BETWEEN 3 AND 100")
    op.execute("DELETE FROM hotel WHERE id BETWEEN 3 AND 100")
