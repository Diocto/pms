# [F05] 코드리뷰 라운드 2

- 날짜: 2026-08-15
- 대상 커밋: 8f0deaf (라운드1 반영분)
- 리뷰어: concurrency-reviewer / domain-reviewer / architecture-reviewer
- 검사 모집단: concurrency 14파일, domain 13파일+대조문서 3, architecture 13파일+grep 전수+vitest·tsc·build 직접 실행

## 요약

| 리뷰어 | 심각 | 중요 | 제안 | 판정 |
|---|---|---|---|---|
| concurrency-reviewer | 0 | 1 | 3 | 통과 (조건부 — 중요 1건 T6 전 수정) |
| domain-reviewer | 0 | 2 | 3 | 재작업 |
| architecture-reviewer | 0 | 0 | 3 | 통과 |

**라운드1 지적 검증: 세 리뷰어 합산 전 항목 "고쳐짐"** (도메인의 전이 전수 테스트 1건만 "미흡" — 이번 라운드 중요로 승격되어 아래에서 처리).

**종합 판정: 재작업 → 전 건 수정 완료** (이 문서 커밋에 포함). 수정 후 테스트 106건·`tsc --noEmit`·`next build` 전부 통과.

## 중요 지적과 처리

### [중요-1] 전이 표 전수 순회가 부분적 — CHECKED_IN+CANCEL(재고 복원 금지 칸) 미검증 (domain)

- **문제:** "도달 가능 칸 전수"를 주장했지만 24칸 중 15칸만 검증. cancel 분기가 if 사슬이라 CHECKED_IN 취소가 뚫리는 회귀(이미 팔린 밤의 재고 복원)를 잡을 테스트가 없었다.
- **처리: 수정함** — `(상태 6 × 이벤트 4)` 24칸 테이블 주도 테스트 신설 (`mock-backend.test.ts` 「전이 표 — 24칸 전수」). 거부 칸은 409 + `INVALID_STATE_TRANSITION` 코드까지, CHECKED_IN+cancel은 **재고 불변**까지 별도 단언. 테스트 81→106건.

### [중요-2] rebook이 과거 날짜를 실어 검색 400 막다른 길 — 라운드1 수정 2건의 상호작용 회귀 (domain)

- **문제:** 생성은 진행 중 투숙(checkIn 과거)을 허용(D21)하고 검색은 과거를 400으로 막는데, rebook이 예약의 checkIn을 그대로 검색 URL에 실어 "같은 조건으로 다시 예약"이 오류 화면으로 끝난다.
- **처리: 수정함** — rebook 날짜를 오늘 기준으로 보정(checkIn 클램프, checkOut < checkIn+1이면 +1일). "다른 날짜 검색"(사용자 취소)은 라벨 의도대로 날짜를 싣지 않아 자동 검색이 발화하지 않는다. (`app/reservations/[code]/page.tsx`, 날짜 유틸은 `lib/dates.ts`로 추출 — 검색 화면과 공용)

### [중요-3] 만료 재조회가 무간격·무상한 폴링 루프 (concurrency — 라운드1 00:00 정지 수정의 회귀)

- **문제:** 브라우저 시계가 서버보다 빠르면 0으로 마운트된 Countdown이 `onExpired → GET → 재마운트 → onExpired`를 지연 없이 반복. mock에서는 재현되지 않고 T6 실 백엔드에서 터지는 종류.
- **처리: 수정함 (T6 전 조건 이행)** — 0으로 **마운트된** 경우의 재조회는 1초 지연을 강제해 최악에도 1req/s로 상한. 자연 카운트다운으로 0에 도달한 첫 회는 즉시 유지.

## 제안 처리 (9건)

| 지적 | 리뷰어 | 처리 |
|---|---|---|
| userId 변경이 키만 재발급하고 화면 상태(오류 카드)는 남김 | conc | 수정함 — userId 변경 시 화면도 idle로 초기화 |
| 화면의 "요청 번호"가 실제 전송 키와 어긋남 (ref 재발급이 렌더에 반영 안 됨) | conc | 수정함 — 키를 useState로 관리해 표시·전송 단일화, 마운트 직후 재발급 제거 |
| 상세 화면 응답의 last-write-wins 경합 (자동 재조회 vs 사용자 액션) | conc | 수정함 — 요청 순번(reqSeq)으로 낡은 응답 폐기 |
| mock 재고 키 날짜 라벨 하루 어긋남 (UTC 변환 함정) | domain | 수정함 — 날짜 산술을 UTC 순수 연산으로 교체 |
| 판매 종료 경계 "2026-10-30" 리터럴 2곳 | domain·arch | 수정함 — `SALES_CHECKOUT_LIMIT = SALES_OPEN_UNTIL + 1일`로 유도 |
| api.test 주석이 옛 횟수("세 번") | domain | 수정함 |
| 테스트 파일이 타입 검사 게이트 밖 + `tsc --noEmit` 실패 (as 캐스트 4곳) | arch | 수정함 — `vi.fn<typeof fetch>`로 캐스트 제거, `npm run typecheck` 스크립트 추가, 통과 확인 |
| `messageFor`의 넓히기 캐스트 | arch | 수정함 — 타입 가드(`isKnownCode`)로 교체, as 0 |
| (재확인) messageFor 캐스트의 규칙 위반 여부 | arch | 위반 아님 판정 (단언 금지는 서버 응답 경계 한정) — 그래도 가드로 교체 |

## 반박

없음 — 이번 라운드 지적은 전부 타당했다.

## 다음 라운드로 넘긴 것

없음. (라운드1에서 미룬 "10분"·"1실 4명" 문구의 T6 재검토는 유지)
