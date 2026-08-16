# PMS 프론트엔드 — 실행 방법

Docker와 Python 3.12+, Node 20+가 필요합니다. 저장소 루트에서:

```bash
# 1) 인프라 + 백엔드 (루트에서)
docker compose up -d                   # MySQL 8.4, Redis 7.4
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head         # 스키마 + 시드 (호텔 100곳·객실타입 299종)
.venv/bin/uvicorn app.main:app --port 8000

# 2) 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev                            # http://localhost:3000
```

터미널을 닫아도 살아 있게 하려면 (백그라운드 기동):

```bash
nohup .venv/bin/uvicorn app.main:app --port 8000 --workers 1 > /tmp/pms-api.log 2>&1 &
cd frontend && nohup npm run dev > /tmp/pms-web.log 2>&1 &
# 내리기: pkill -f "uvicorn app.main:app"; pkill -f "next dev"
```

- 위 명령은 2026-08-17에 실제 실행으로 검증했다.
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

- 마지막 전 구간 검증: **2026-08-17 — 10단계 전부 통과** (캐시 DB→CACHE · 생성 201 ·
  fresh 재검색 재고 차감 · 확정 · 취소 복원 · 판매 전 · 인원 초과 · 호텔 목록 100곳 ·
  user_id 목록/결제 완료 필터 · 확장 호텔 객실 왕복)

## 데이터 초기화 (재시드)

부하테스트·시연으로 재고가 소진됐을 때 처음 상태로 되돌리려면 (F01 스펙 1.9 (5)):

```bash
docker compose down -v && docker compose up -d   # 볼륨까지 삭제
.venv/bin/alembic upgrade head                    # 스키마+시드 재적용 (재고 26,910행)
```

시드 날짜가 고정(2026-08-01~10-29)이라 몇 번을 돌려도 같은 상태가 나온다.

**재시드하면 예약이 0건이 된다.** 「내 예약」 화면을 열어 보려면 시연용 예약을 만든다
(서버 두 개가 떠 있어야 한다):

```bash
python3 frontend/demo-seed.py
```

`user-1001` 앞으로 네 가지 상태의 예약을 만든다 — **확정 · 결제 대기 · 숙박 완료 · 결제 취소**.
상단 사용자 전환이 `user-1001`이면 「내 예약」에서 이 넷이 보이고, 숙박 완료 건에서는 투숙 리뷰
작성 폼이 열린다. **실제 손님 기록이 아니라 화면을 보여주려고 만든 시연 데이터다** — 만들지
않으면 「내 예약」이 비어 있는 것이 정상이다.

## 시연 포인트

- 검색(예: 2026-09-01→09-04, 2명) → 호텔 선택 → 객실 선택 → 예약하기 → 상세에서 10분 카운트다운 → 결제하기(내부 모의 결제) → 확정.
- **결제 취소**: 확정된 예약의 상세에서 [예약 취소] → 2단 확인 → "결제 취소" 화면 (결제도 함께 취소, 재고 복원).
- **내 예약**: 상단 "내 예약" — **사용자 식별값(X-User-Id)으로 서버 DB에서 직접 조회** (GET /api/reservations, PR #38). "결제 완료" 탭은 서버 status 필터. 식별값을 바꾸면 그 사용자의 예약이 보인다.
- **호텔 100곳**: 검색은 날짜 입력 → 호텔 목록(GET /api/hotels, 이름 필터) → 호텔 선택 시 그 호텔만 잔여 조회. 확장 호텔(003~100)의 객실타입 id는 호텔id×1000+n.
- **디자인**: 시안 1 「세리프 리조트」 채택(관리자 컨펌) — 크림·딥 포레스트·골드, 세리프 헤드라인. 원본 시안: docs/design/redesign/.
- **위시리스트(찜)**: 객실 카드의 ♡ — 브라우저 보관(식별값별), 잔여·가격은 항상 서버 조회. 호텔 목록 위 "찜한 객실"에서 바로 잔여 조회.
- **투숙 리뷰 (더미 API)**: 예약 상세 하단 — 목록·평균은 누구나, 작성은 숙박 완료(CHECKED_OUT) 예약에서만(서버 상태로 게이트). 실 백엔드에 없는 체험 기능이라 저장은 휘발성이다.
- 재고 부족(409) 흐름: 스위트(10실)를 여러 번 예약해 소진시키면 "방금 마감 → 자동 재확인 → 재시도 → 마감 안내"가 재현된다. (mock 모드에서는 사용자 `user-409` 직접 입력으로도 강제 가능)
- 상단 "사용자(과제용 식별값)"가 `X-User-Id` 헤더다 — **인증이 아니다** (ADR-0006, 과제 범위 밖).
