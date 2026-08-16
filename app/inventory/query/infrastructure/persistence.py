"""가용 객실 집계 쿼리 어댑터 (스펙 8절).

생 SQL 1발이다. F01의 SQLModel 테이블 클래스를 import하지 않는다 (D2) —
같은 테이블을 이름으로만 읽으므로, F01이 모델을 바꿔도 스키마가 그대로면
이 쿼리는 그대로다. 세션은 주입받아 쓰기만 하고 스스로 열지 않는다.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.inventory.query.application.commands import (
    AvailabilityDiagnosis,
    AvailableRoomTypeView,
    SearchAvailableRoomsQuery,
)

# HAVING COUNT(*) = :nights 가 이 쿼리의 심장이다. 재고 행이 없는 날짜는
# "제약 없음"이 아니라 "가용 아님"이다 (D9 fail-closed). 잠금 절이 없는
# 이유는 D3 — 정확성은 예약 시점의 조건부 UPDATE가 책임진다.
_SEARCH_SQL = text(
    """
    SELECT rt.id            AS room_type_id,
           rt.name          AS room_type_name,
           rt.capacity      AS capacity,
           rt.base_price    AS price_per_night,
           MIN(i.remaining) AS min_remaining
      FROM room_daily_inventory i
      JOIN room_type rt ON rt.id = i.room_type_id
     WHERE rt.hotel_id  = :hotel_id
       AND i.stay_date >= :check_in
       AND i.stay_date <  :check_out
       AND rt.capacity * :room_count >= :guest_count
     GROUP BY rt.id, rt.name, rt.capacity, rt.base_price
    HAVING COUNT(*)        = :nights
       AND MIN(i.remaining) >= :room_count
     ORDER BY rt.base_price ASC, rt.id ASC
    """
)


# 집계가 비었을 때만 나간다 — 정상 경로는 쿼리 1회를 유지한다 (스펙 8절)
_DIAGNOSE_SQL = text(
    """
    SELECT COUNT(DISTINCT rt.id)                                  AS room_type_count,
           COUNT(DISTINCT CASE WHEN rt.capacity * :room_count >= :guest_count
                               THEN rt.id END)                    AS fitting_room_type_count,
           MAX(i.stay_date)                                       AS sales_open_until
      FROM room_type rt
      LEFT JOIN room_daily_inventory i ON i.room_type_id = rt.id
     WHERE rt.hotel_id = :hotel_id
    """
)


class MySqlAvailabilityQueryAdapter:
    def search(
        self, session: Session, query: SearchAvailableRoomsQuery
    ) -> list[AvailableRoomTypeView]:
        nights = query.stay.nights()
        rows = session.execute(
            _SEARCH_SQL,
            {
                "hotel_id": query.hotel_id,
                "check_in": query.stay.check_in,
                "check_out": query.stay.check_out,
                "guest_count": query.guest_count,
                "room_count": query.room_count,
                "nights": nights,
            },
        ).mappings()
        return [
            AvailableRoomTypeView(
                room_type_id=row["room_type_id"],
                room_type_name=row["room_type_name"],
                capacity=row["capacity"],
                min_remaining=row["min_remaining"],
                price_per_night=row["price_per_night"],
                # 총액 = 단가 × 박수 × 객실 수 (스펙 8절) — F01 예약 청구액과 같은 식
                total_price=row["price_per_night"] * nights * query.room_count,
            )
            for row in rows
        ]

    def diagnose(
        self, session: Session, query: SearchAvailableRoomsQuery
    ) -> AvailabilityDiagnosis:
        row = session.execute(
            _DIAGNOSE_SQL,
            {
                "hotel_id": query.hotel_id,
                "guest_count": query.guest_count,
                "room_count": query.room_count,
            },
        ).mappings().one()
        return AvailabilityDiagnosis(
            room_type_count=row["room_type_count"],
            fitting_room_type_count=row["fitting_room_type_count"],
            sales_open_until=row["sales_open_until"],
        )
