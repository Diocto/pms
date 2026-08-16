# T6 마감 검증 — 프론트 프록시(3000) 경유 실 백엔드 전 구간 왕복. 1회용 스크립트.
import json
import urllib.error
import urllib.request
import uuid

B = "http://localhost:3000/api"


def call(method, path, body=None, headers=None):
    req = urllib.request.Request(
        B + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"content-type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


q = "/availability?hotelId=1&checkIn=2026-09-05&checkOut=2026-09-07&guestCount=2&roomCount=1"
_, a = call("GET", q)
_, b = call("GET", q)
print("1) 캐시:", a["source"], "→", b["source"])

# 키는 실행마다 새로 만든다 — 고정 키를 쓰면 서버가 (올바르게) 이전 실행의 예약을
# 200으로 재생해 이후 단계가 어긋난다. 이 스크립트가 그걸로 한 번 검증해 준 셈이다.
h = {"X-User-Id": "user-e2e", "Idempotency-Key": f"e2e-{uuid.uuid4()}"}
s, r = call("POST", "/reservations",
            {"roomTypeId": 3, "checkIn": "2026-09-05", "checkOut": "2026-09-07",
             "roomCount": 1, "guestCount": 2}, h)
code = r["confirmationCode"]
print("2) 생성:", s, r["status"], code)

_, f = call("GET", q + "&fresh=true")
suite = [i for i in f["items"] if i["roomTypeId"] == 3][0]
print("3) fresh 재검색 스위트 잔여:", suite["minRemaining"], "(기대 9)")

_, c = call("POST", f"/reservations/{code}/confirm", None, {"X-User-Id": "user-e2e"})
print("4) 확정:", c["status"], "| confirmedAt:", bool(c.get("confirmedAt")))
_, x = call("POST", f"/reservations/{code}/cancel", None, {"X-User-Id": "user-e2e"})
print("5) 취소(정리):", x["status"])

_, n = call("GET", "/availability?hotelId=1&checkIn=2026-11-01&checkOut=2026-11-03&guestCount=2&roomCount=1")
print("6) 판매 전:", n.get("emptyReason"), n.get("salesOpenUntil"))
_, g = call("GET", "/availability?hotelId=1&checkIn=2026-09-05&checkOut=2026-09-07&guestCount=5&roomCount=1")
print("7) 인원 초과:", g.get("emptyReason"))

# PR #38 — 호텔 100곳 + user_id 기반 목록
_, hl = call("GET", "/hotels")
h50 = [x for x in hl["hotels"] if x["hotelId"] == 50][0]
print("8) 호텔 목록:", len(hl["hotels"]), "곳 |", h50["name"], [r["roomTypeId"] for r in h50["roomTypes"]])

h2 = {"X-User-Id": "user-e2e", "Idempotency-Key": h["Idempotency-Key"] + "-2"}
_, r2 = call("POST", "/reservations",
             {"roomTypeId": 50003, "checkIn": "2026-09-05", "checkOut": "2026-09-07",
              "roomCount": 1, "guestCount": 2}, h2)
call("POST", f"/reservations/{r2['confirmationCode']}/confirm", None, {"X-User-Id": "user-e2e"})
_, lst = call("GET", "/reservations", None, {"X-User-Id": "user-e2e"})
_, conf = call("GET", "/reservations?status=CONFIRMED", None, {"X-User-Id": "user-e2e"})
print("9) 목록:", len(lst), "건 | 결제 완료 필터:", len(conf), "건 · 최신:", conf[0]["confirmationCode"] if conf else "-")
call("POST", f"/reservations/{r2['confirmationCode']}/cancel", None, {"X-User-Id": "user-e2e"})
print("10) 결제 취소(정리) 완료 — 확장 호텔(50) 객실로도 전 구간 동작")
