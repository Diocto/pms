"""검색 API 통합 — 라우터부터 DB까지 (TDD 20·20b, T8).

응답 본문의 키·값을 **생 문자열로 직접** 확인한다. camelCase 누락도
`source` 오기도 상태 코드는 정상이라 조용하고, 부하테스트·화면 쪽에서만 죽는다.
시드에 의존하지 않는다 — 전용 호텔 933을 만들고 지운다.
"""

from datetime import date, timedelta

import pytest
import redis as redis_library
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app

HOTEL_ID = 933
ROOM_TYPE_ID = 9331  # capacity 2, 총 5실, 100,000원
CHECK_IN = date(2026, 9, 1)
CHECK_OUT = date(2026, 9, 4)


@pytest.fixture(scope="module")
def engine(database_url):
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO hotel (id, name, address, created_at)"
                " VALUES (:id, '검색 API 테스트 호텔', '검색 테스트 주소', NOW(6))"
            ),
            {"id": HOTEL_ID},
        )
        conn.execute(
            text(
                "INSERT INTO room_type"
                " (id, hotel_id, name, capacity, total_quantity, base_price,"
                "  created_at)"
                " VALUES (:id, :hotel, '검색 API 타입', 2, 5, 100000, NOW(6))"
            ),
            {"id": ROOM_TYPE_ID, "hotel": HOTEL_ID},
        )
        for offset in range(3):
            conn.execute(
                text(
                    "INSERT INTO room_daily_inventory"
                    " (room_type_id, stay_date, total_quantity, remaining,"
                    "  created_at, updated_at)"
                    " VALUES (:id, :d, 5, 5, NOW(6), NOW(6))"
                ),
                {"id": ROOM_TYPE_ID, "d": CHECK_IN + timedelta(days=offset)},
            )
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM room_daily_inventory WHERE room_type_id = :id"),
            {"id": ROOM_TYPE_ID},
        )
        conn.execute(
            text("DELETE FROM room_type WHERE id = :id"), {"id": ROOM_TYPE_ID}
        )
        conn.execute(text("DELETE FROM hotel WHERE id = :id"), {"id": HOTEL_ID})
    engine.dispose()


@pytest.fixture(scope="module")
def client(engine, database_url, redis_url):
    # module 스코프라 monkeypatch 대신 os.environ을 직접 만지고 되돌린다
    import os

    saved = {k: os.environ.get(k) for k in ("PMS_DATABASE_URL", "PMS_REDIS_URL")}
    os.environ["PMS_DATABASE_URL"] = database_url
    os.environ["PMS_REDIS_URL"] = redis_url
    redis_client = redis_library.Redis.from_url(redis_url)
    redis_client.flushdb()
    redis_client.close()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _search(client, **overrides):
    params = {
        "hotelId": HOTEL_ID,
        "checkIn": str(CHECK_IN),
        "checkOut": str(CHECK_OUT),
        "guestCount": 2,
        "roomCount": 1,
    }
    params.update(overrides)
    params = {k: v for k, v in params.items() if v is not None}  # None이면 생략
    return client.get("/api/availability", params=params)


# --- TDD 20. 200 — 본문 키가 camelCase이고 source가 계약값이다 ---


def test_T20_200_본문_키가_camelCase다(client):
    response = _search(client)
    assert response.status_code == 200, response.text
    body = response.json()
    # 키 문자열을 그대로 확인한다 — ApiModel 상속이 빠지면 snake_case로 나간다
    for key in (
        "hotelId",
        "checkIn",
        "checkOut",
        "nights",
        "guestCount",
        "roomCount",
        "searchedAt",
        "source",
        "staleToleranceSeconds",
        "items",
    ):
        assert key in body, f"응답에 {key}가 없다: {sorted(body)}"
    item = body["items"][0]
    for key in (
        "roomTypeId",
        "roomTypeName",
        "capacity",
        "minRemaining",
        "pricePerNight",
        "totalPrice",
    ):
        assert key in item, f"항목에 {key}가 없다: {sorted(item)}"
    assert "room_type_id" not in item


def test_T20_요청_에코와_계산_필드가_맞다(client):
    body = _search(client).json()
    assert body["hotelId"] == HOTEL_ID
    assert (body["checkIn"], body["checkOut"]) == (str(CHECK_IN), str(CHECK_OUT))
    assert body["nights"] == 3
    item = body["items"][0]
    assert item["roomTypeId"] == ROOM_TYPE_ID
    assert item["minRemaining"] == 5
    assert (item["pricePerNight"], item["totalPrice"]) == (100000, 300000)


def test_T20_source_값은_CACHE_또는_DB다(client):
    # 부하테스트가 이 두 문자열로 히트율을 센다. 표본이 말라도 임계값 검사는
    # 조용히 통과하므로, 키 존재와 값 집합을 여기서 못 박는다 (8절)
    body = _search(client).json()
    assert body["source"] in ("CACHE", "DB")


def test_T20_빈_결과에는_emptyReason이_붙는다(client):
    body = _search(client, guestCount=5).json()  # capacity 2 × 1실 < 5
    assert body["items"] == []
    assert body["emptyReason"] == "NO_FITTING_ROOM_TYPE"


def test_T20_가용_있는_응답에는_emptyReason_키_자체가_없다(client):
    body = _search(client).json()
    assert "emptyReason" not in body
    assert "salesOpenUntil" not in body


def test_T20_판매_전이면_salesOpenUntil이_붙는다(client):
    body = _search(
        client, checkIn="2026-09-02", checkOut="2026-09-06"
    ).json()  # 재고 마지막 날짜 9/3, 마지막 밤 9/5
    assert body["emptyReason"] == "NOT_YET_OPEN"
    assert body["salesOpenUntil"] == "2026-09-03"


def test_T20_fresh_파라미터를_받는다(client):
    response = _search(client, fresh="true")
    assert response.status_code == 200
    assert response.json()["source"] == "DB"


def test_T20_roomCount는_선택이고_기본값은_1이다(client):
    # 계약 문서 2절: "선택 | 1 ~ 10 (기본 1)". 부하테스트·화면가 생략하고 부른다
    response = _search(client, roomCount=None)
    assert response.status_code == 200, response.text
    assert response.json()["roomCount"] == 1


def test_T20_인원_객실_수_상한_경계는_200이다(client):
    assert _search(client, guestCount=20).status_code == 200
    assert _search(client, guestCount=20, roomCount=10).status_code == 200


# --- TDD 20. 400 · 404 — code 문자열 직접 비교 ---


def test_T20_인원_객실_수가_상한을_넘으면_400이다(client):
    # 스펙 6절: guestCount 1~20, roomCount 1~10. 범위 밖은 400 INVALID_REQUEST
    over_guest = _search(client, guestCount=21)
    assert over_guest.status_code == 400
    assert over_guest.json()["code"] == "INVALID_REQUEST"
    over_room = _search(client, roomCount=11)
    assert over_room.status_code == 400
    assert over_room.json()["code"] == "INVALID_REQUEST"


def test_T20_과거_체크인은_400_INVALID_REQUEST다(client):
    response = _search(client, checkIn="2020-01-01", checkOut="2020-01-03")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_T20_역전된_기간은_400이다(client):
    response = _search(client, checkIn="2026-09-04", checkOut="2026-09-01")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_T20_형식이_틀리면_422가_아니라_400이다(client):
    response = _search(client, guestCount="다섯")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_T20_없는_호텔은_404_RESOURCE_NOT_FOUND다(client):
    response = _search(client, hotelId=999933)
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert "traceId" in body


# --- TDD 20b. 기여자 등록 — 공용 설정 응답에 검색 몫이 실린다 ---


def test_T20b_공용_설정_응답에_검색_기여분이_실린다(client):
    body = client.get("/api/internal/config").json()
    # 키는 조작자가 셸에 치는 환경변수 이름 그대로다 (설정 키 예외)
    assert body["loadTest"]["PMS_SEARCH_CACHE_ENABLED"] is True
    assert body["loadTest"]["PMS_SEARCH_CACHE_TTL_SECONDS"] == 10
    assert body["implementations"]["searchCache"] == "RedisAvailabilityCacheAdapter"
    # 검색은 카운터를 싣지 않는다 (D15) — 검색 접두 키가 없어야 한다
    assert not [k for k in body["counters"] if "search" in k.lower()]
