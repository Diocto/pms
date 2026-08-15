# PMS 프론트엔드 — 실행 방법

Docker와 Python 3.12+, Node 20+가 필요합니다. 저장소 루트에서:

```bash
# 1) 인프라 + 백엔드 (루트에서)
docker compose up -d                   # MySQL 8.4, Redis 7.4
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head         # 스키마 + 시드 (호텔 2곳·객실 5종·재고 450행)
.venv/bin/uvicorn app.main:app --port 8000

# 2) 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev                            # http://localhost:3000
```

- 위 명령은 2026-08-16에 실제 실행으로 검증했다.
- 백엔드 확인: `curl localhost:8000/health` → `{"status":"UP"}`. Swagger: http://localhost:8000/docs
- 프론트의 `/api/*` 호출은 Next 프록시가 백엔드(8000)로 넘긴다. 백엔드 포트를 바꾸면
  `PMS_BACKEND_ORIGIN=http://localhost:포트 npm run dev`.

## API 모드 (`frontend/.env.development`의 `NEXT_PUBLIC_API_MODE`)

| 값 | 의미 |
|---|---|
| `real` (현재) | 전부 실 백엔드 — 검색·예약·확정·취소 전 구간 |
| `hybrid` | 검색만 가짜, 예약 계열은 실 백엔드 (F03 병합 전 구간에서 쓰던 모드) |
| `mock` | 전부 가짜 — 백엔드 없이 화면·실패 시나리오 시연 |

전 구간 왕복은 `python3 frontend/e2e-check.py`로 재검증할 수 있다 (서버 두 개가 떠 있어야 한다).

## 시연 포인트

- 검색(예: 2026-09-01→09-04, 2명) → 호텔 선택 → 객실 선택 → 예약하기 → 상세에서 10분 카운트다운 → 결제하기(내부 모의 결제) → 확정 / 예약 취소.
- 재고 부족(409) 흐름: 스위트(10실)를 여러 번 예약해 소진시키면 "방금 마감 → 자동 재확인 → 재시도 → 마감 안내"가 재현된다. (mock 모드에서는 사용자 `user-409` 직접 입력으로도 강제 가능)
- 상단 "사용자(과제용 식별값)"가 `X-User-Id` 헤더다 — **인증이 아니다** (ADR-0006, 과제 범위 밖).
