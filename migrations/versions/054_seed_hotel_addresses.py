"""시드 주소 정정 — 호텔 3~100을 실제 지역으로 흩는다

리비전 053이 호텔 3~100의 주소를 전부 `서울특별시 테스트구 예약로 N`으로 찍었다.
그런데 프론트 검색 화면이 이 주소를 그대로 노출한다(`frontend/app/search/page.tsx`).
검토관이 화면을 열면 호텔 98곳이 전부 "테스트구"에 있는 것으로 보인다.

**규칙 생성이라는 성질은 그대로 둔다** (예약 코어 스펙 1.9절 "전부 규칙에서 유도된다").
바뀌는 것은 규칙이 만들어내는 값뿐이고, 지역별 접두 문자열을 id 대역으로 고른다.

건드리지 않는 것:
- 호텔 1·2 — 리비전 051이 넣은 진짜 같은 주소가 이미 있고, `tests/test_api_hotels.py`가
  호텔 1의 주소를 단언한다
- 스키마, 객실타입, 재고 — 주소 문자열만 바꾼다
- 리비전 053 파일 자체 — 이미 적용된 마이그레이션은 수정하지 않는다
  (`docs/architecture/parallel-work.md`)

지역 분포는 `docs/reports/F07-지역검색-기획.md` D5 표를 따른다. 관광 수요가 큰 곳에
많이 배정했고, 어느 지역도 5곳 밑으로 내려가지 않는다.

**지역 컬럼은 만들지 않는다.** 그건 지역 검색 지역 검색 기능이고 스펙으로만 남기기로
했다(ADR-0061과 같은 처리). 이 리비전은 데이터 정정 하나뿐이라 API 응답 형태도
바뀌지 않는다.

리비전 ID: 054_seed_hotel_addresses
"""

from alembic import op

revision = "054_seed_hotel_addresses"
down_revision = "053_seed_hotels_extension"
branch_labels = None
depends_on = None

# (시작 id, 끝 id, 이름 접두, 주소 접두) — 합계 98곳 (3~100)
REGIONS = [
    (3, 23, "서울", "서울특별시 중구 세종대로"),
    (24, 36, "부산", "부산광역시 해운대구 해운대해변로"),
    (37, 52, "제주", "제주특별자치도 제주시 중앙로"),
    (53, 64, "강원", "강원특별자치도 속초시 중앙로"),
    (65, 72, "경기", "경기도 고양시 일산동구 중앙로"),
    (73, 78, "인천", "인천광역시 연수구 컨벤시아대로"),
    (79, 84, "경주", "경상북도 경주시 첨성로"),
    (85, 89, "전주", "전라북도 전주시 완산구 어진길"),
    (90, 95, "여수", "전라남도 여수시 돌산로"),
    (96, 100, "대구", "대구광역시 중구 동성로"),
]


def upgrade() -> None:
    for lo, hi, name_prefix, addr_prefix in REGIONS:
        # 이름도 함께 바꾼다. 주소는 제주인데 이름이 '호텔 037'이면 화면에서
        # 지역을 알아볼 단서가 이름에 없다 — 목록을 훑는 사람이 쓰는 단서는 이름이다.
        op.execute(
            f"""
            UPDATE hotel
               SET name = CONCAT('{name_prefix} 호텔 ', LPAD(id, 3, '0')),
                   address = CONCAT('{addr_prefix} ', id)
             WHERE id BETWEEN {lo} AND {hi}
            """
        )


def downgrade() -> None:
    # 053이 찍었던 값 그대로 되돌린다
    op.execute(
        """
        UPDATE hotel
           SET name = CONCAT('호텔 ', LPAD(id, 3, '0')),
               address = CONCAT('서울특별시 테스트구 예약로 ', id)
         WHERE id BETWEEN 3 AND 100
        """
    )
