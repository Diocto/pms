"""시드 — 호텔 2곳, 객실타입 5종 (스펙 1.9절 (2)(3))

id를 명시해 넣는다. 선착순 특가·검색·부하테스트가 이 id를 상수로 박기 때문에
AUTO_INCREMENT에 맡기지 않는다.

`id = 3`(스위트, 10실)이 경합 실험용이다 — 재고가 전부 넉넉하면 경합이
일어나지 않아 아무것도 증명하지 못한다. `id = 5`(20실)는 보조 경합 대상.

리비전 ID: 051_seed_hotel_room_type
"""

from alembic import op

revision = "051_seed_hotel_room_type"
down_revision = "004_reservation_history_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO hotel (id, name, address, created_at) VALUES
          (1, '서울 그랜드 호텔', '서울특별시 중구 을지로 100', NOW(6)),
          (2, '부산 오션뷰 호텔', '부산광역시 해운대구 해운대해변로 200', NOW(6))
        """
    )
    op.execute(
        """
        INSERT INTO room_type
          (id, hotel_id, name, capacity, total_quantity, base_price, created_at)
        VALUES
          (1, 1, '스탠다드',        2, 100, 150000, NOW(6)),
          (2, 1, '디럭스',          3,  50, 250000, NOW(6)),
          (3, 1, '스위트',          4,  10, 600000, NOW(6)),
          (4, 2, '오션뷰 스탠다드', 2,  80, 180000, NOW(6)),
          (5, 2, '오션뷰 스위트',   4,  20, 450000, NOW(6))
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM room_type WHERE id IN (1, 2, 3, 4, 5)")
    op.execute("DELETE FROM hotel WHERE id IN (1, 2)")
