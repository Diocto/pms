"""호텔 목록 API 통합 — GET /api/hotels (F05 검색 화면용, 관리자 지시 2026-08-16).

계약: 인증 없이 호출한다(검색과 같은 익명 경로). 응답은 호텔 배열이고
호텔마다 객실타입 매핑이 붙는다. 정렬은 호텔 id 오름차순, 그 안에서
객실타입 id 오름차순 — F05가 이 순서를 그대로 그린다.

이 테스트는 예외적으로 **시드에 의존한다** — 검증 대상이 시드 계약
그 자체(호텔 100곳, 확장 규칙)이기 때문이다. 전용 행을 만들지 않는다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client(database_url, redis_url, monkeypatch):
    monkeypatch.setenv("PMS_DATABASE_URL", database_url)
    monkeypatch.setenv("PMS_REDIS_URL", redis_url)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def hotels(client) -> list[dict]:
    response = client.get("/api/hotels")  # X-User-Id 없이 — 익명 경로다
    assert response.status_code == 200
    return response.json()["hotels"]


def test_호텔_100곳이_id_오름차순으로_나온다(hotels):
    assert len(hotels) == 100
    assert [hotel["hotelId"] for hotel in hotels] == list(range(1, 101))


def test_기존_시드_호텔의_계약이_그대로_실려_나온다(hotels):
    seoul = hotels[0]
    assert seoul["name"] == "서울 그랜드 호텔"
    assert seoul["address"] == "서울특별시 중구 을지로 100"
    assert [room_type["roomTypeId"] for room_type in seoul["roomTypes"]] == [1, 2, 3]
    suite = seoul["roomTypes"][2]
    assert suite == {
        "roomTypeId": 3,
        "name": "스위트",
        "capacity": 4,
        "totalQuantity": 10,  # 경합 실험용 소량 재고 — 시드 계약 1.9절 (3)
        "basePrice": 600000,
    }
    busan = hotels[1]
    assert [room_type["roomTypeId"] for room_type in busan["roomTypes"]] == [4, 5]


def test_확장_호텔은_규칙적인_이름과_객실타입_id를_갖는다(hotels):
    # 규칙: 호텔 h(3~100)의 객실타입 id는 h*1000 + {1,2,3}. F05가 이 규칙으로
    # 매핑 상수를 생성할 수 있어야 한다
    hotel_50 = hotels[49]
    assert hotel_50["hotelId"] == 50
    assert hotel_50["name"] == "호텔 050"
    assert [room_type["roomTypeId"] for room_type in hotel_50["roomTypes"]] == [
        50001,
        50002,
        50003,
    ]
    assert [
        (
            room_type["name"],
            room_type["capacity"],
            room_type["totalQuantity"],
            room_type["basePrice"],
        )
        for room_type in hotel_50["roomTypes"]
    ] == [
        ("스탠다드", 2, 50, 150000),
        ("디럭스", 3, 30, 250000),
        ("스위트", 4, 10, 400000),
    ]


def test_모든_확장_호텔이_같은_객실타입_구성을_갖는다(hotels):
    # 한 호텔만 찍어 보면 나머지 97곳이 무방비다 — 전 호텔을 규칙으로 순회한다
    for hotel in hotels[2:]:
        hotel_id = hotel["hotelId"]
        assert hotel["name"] == f"호텔 {hotel_id:03d}"
        assert [room_type["roomTypeId"] for room_type in hotel["roomTypes"]] == [
            hotel_id * 1000 + 1,
            hotel_id * 1000 + 2,
            hotel_id * 1000 + 3,
        ]
