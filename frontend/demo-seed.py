# 시연용 예약 데이터 생성 — user-1001 계정에 상태별 예약 4건.
# 부하테스트 재시드로 시연 데이터가 지워졌을 때 다시 돌린다.
# 상태 구성: 확정(결제 취소 시연) / 결제 대기(10분 뒤 '시간 초과'로 보임) /
#            숙박 완료(리뷰 작성 게이트 시연) / 결제 취소.
import json
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

B = "http://localhost:3000/api"
U = "user-1001"


def call(method, path, body=None, headers=None):
    req = urllib.request.Request(
        B + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"content-type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def hdr():
    return {"X-User-Id": U, "Idempotency-Key": f"demo-{uuid.uuid4()}"}


today = date.today()

_, a = call("POST", "/reservations", {"roomTypeId": 3, "checkIn": "2026-09-12", "checkOut": "2026-09-14", "roomCount": 1, "guestCount": 2}, hdr())
call("POST", f"/reservations/{a['confirmationCode']}/confirm", None, {"X-User-Id": U})
print("확정:", a["confirmationCode"])

_, b = call("POST", "/reservations", {"roomTypeId": 1, "checkIn": "2026-09-20", "checkOut": "2026-09-21", "roomCount": 1, "guestCount": 2}, hdr())
print("결제대기(만료 예정):", b["confirmationCode"])

stay_in, stay_out = str(today), str(today + timedelta(days=1))
_, c = call("POST", "/reservations", {"roomTypeId": 3, "checkIn": stay_in, "checkOut": stay_out, "roomCount": 1, "guestCount": 2}, hdr())
call("POST", f"/reservations/{c['confirmationCode']}/confirm", None, {"X-User-Id": U})
call("POST", f"/reservations/{c['confirmationCode']}/check-in", None, {"X-User-Id": U})
s, _ = call("POST", f"/reservations/{c['confirmationCode']}/check-out", None, {"X-User-Id": U})
print("숙박완료:", c["confirmationCode"], "(체크아웃", s, ")")

_, d = call("POST", "/reservations", {"roomTypeId": 2, "checkIn": "2026-09-25", "checkOut": "2026-09-26", "roomCount": 1, "guestCount": 2}, hdr())
call("POST", f"/reservations/{d['confirmationCode']}/confirm", None, {"X-User-Id": U})
call("POST", f"/reservations/{d['confirmationCode']}/cancel", None, {"X-User-Id": U})
print("결제취소:", d["confirmationCode"])

_, lst = call("GET", "/reservations", None, {"X-User-Id": U})
print("user-1001 내 예약 상태:", [r["status"] for r in lst])
