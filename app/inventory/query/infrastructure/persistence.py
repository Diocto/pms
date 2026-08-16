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
    HotelRoomTypeView,
    HotelView,
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


# 호텔 목록 — 정적 마스터 조인 1발. 재고 테이블은 건드리지 않는다 (그건 검색의 일).
# 정렬이 곧 응답 순서다 — F05가 이 순서를 그대로 그린다
_LIST_HOTELS_SQL = text(
    """
    SELECT h.id             AS hotel_id,
           h.name           AS hotel_name,
           h.address        AS address,
           rt.id            AS room_type_id,
           rt.name          AS room_type_name,
           rt.capacity      AS capacity,
           rt.total_quantity AS total_quantity,
           rt.base_price    AS base_price
      FROM hotel h
      JOIN room_type rt ON rt.hotel_id = h.id
     ORDER BY h.id ASC, rt.id ASC
    """
)


class MySqlHotelCatalogAdapter:
    def list_hotels(self, session: Session) -> list[HotelView]:
        rows = session.execute(_LIST_HOTELS_SQL).mappings()
        hotels: list[HotelView] = []
        grouped: dict[int, list[HotelRoomTypeView]] = {}
        heads: dict[int, tuple[str, str]] = {}
        for row in rows:
            hotel_id = row["hotel_id"]
            if hotel_id not in grouped:
                grouped[hotel_id] = []
                heads[hotel_id] = (row["hotel_name"], row["address"])
            grouped[hotel_id].append(
                HotelRoomTypeView(
                    room_type_id=row["room_type_id"],
                    name=row["room_type_name"],
                    capacity=row["capacity"],
                    total_quantity=row["total_quantity"],
                    base_price=row["base_price"],
                )
            )
        for hotel_id, room_types in grouped.items():  # 삽입 순서 = SQL 정렬 순서
            name, address = heads[hotel_id]
            hotels.append(
                HotelView(
                    hotel_id=hotel_id,
                    name=name,
                    address=address,
                    room_types=room_types,
                )
            )
        return hotels


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
                total_price=row["price_per_night"] * nights,
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
