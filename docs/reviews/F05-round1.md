# [F05] 코드리뷰 라운드 1

- 날짜: 2026-08-15
- 대상 커밋: 426669f..cd5c81c (T1~T5 + 교육 노트, `frontend/` 전체)
- 리뷰어: concurrency-reviewer / domain-reviewer / architecture-reviewer
- 검사 모집단: 세 리뷰어 모두 `frontend/` 전 파일(소스 16, 테스트 7)과 시안·브리핑 계약 대조. "검사 안 됨" 영역: 화면 컴포넌트의 렌더링 자체(컴포넌트 테스트 없음 — 완료 보고서의 한계 절에 기재)

## 요약

| 리뷰어 | 심각 | 중요 | 제안 | 판정 |
|---|---|---|---|---|
| concurrency-reviewer | 0 | 1 | 4 | 통과 |
| domain-reviewer | 0 | 4 | 4 | 재작업 |
| architecture-reviewer | 0 | 4 | 5 | 재작업 |

**종합 판정: 재작업** (중요 9건, 중복 1건 제외 실제 8건). 구조 변경은 없고 전부 국소 수정.

세 리뷰 공통 확인: 골격 계약 6종(키 1회 발급·유지, 409 4단계·상한, REQUEST_IN_PROGRESS 같은 키, 200+CANCELLED 비성공, 만료 서버 위임, 상태→행동 매핑의 전이표 일치)은 코드·테스트에서 검증됨.

## 지적 사항 (중요)

### [중요-1] "같은 조건으로 다시 예약"이 호텔을 무조건 서울로 보낸다 (domain + architecture 중복 지적)

- **위치:** `frontend/app/reservations/[code]/page.tsx:229`, 부수 `app/book/page.tsx:44`
- **문제:** rebook 링크에 `hotelId=1` 하드코딩. 부산(roomTypeId 4·5) 예약의 재예약이 서울 검색으로 간다. 주문서의 `hotelId ?? 1` 기본값도 같은 계열 — fresh 재검색이 엉뚱한 호텔을 본다.
- **실패 시나리오:** 부산 오션뷰 예약이 결제 거절/만료된 사용자가 "같은 조건으로 다시 예약" → 서울 그랜드 호텔 결과. 날짜·인원이 유지돼 알아채기 어렵다.
- **조치:** `hotels.ts`에 시드 기반 roomTypeId→hotelId 매핑(1~3→1, 4~5→2) 신설, rebook에 사용. 주문서는 hotelId 없는 진입을 거부. 사용자 취소 화면의 버튼 라벨도 시안대로 "다른 날짜 검색"으로 분리.
- **처리:** 수정함

### [중요-2] REQUEST_IN_PROGRESS 재시도 횟수가 시안 표와 하나 어긋난다 (domain)

- **위치:** `frontend/lib/api.ts:52` (`IN_PROGRESS_MAX_ATTEMPTS = 3` = 총 시도 3회 = 재시도 2회)
- **문제:** 시안 매핑 표의 "자동 최대 N회"를 INSUFFICIENT(재시도 2회)와 REQUEST_IN_PROGRESS(총 3회)에서 다르게 해석했다. 같은 표의 같은 열이 코드에서 다른 의미.
- **조치:** "자동 최대 N회 = 재시도 N회"로 통일. REQUEST_IN_PROGRESS는 재시도 3회(총 4요청)로 수정, 테스트 갱신.
- **처리:** 수정함

### [중요-3] REQUEST_IN_PROGRESS 소진 후 화면이 약속("결과를 확인합니다")을 지키지 않고, 회복 동선이 새 키로 이어진다 (concurrency)

- **위치:** `frontend/app/book/page.tsx:210-224`, `lib/error-messages.ts:31-34`
- **실패 시나리오:** 혼잡으로 재시도가 전부 소진 → 오류 카드의 유일한 버튼 "검색으로 돌아가기" → 새 주문서 = 새 멱등 키 → 서버엔 첫 요청의 PENDING이 이미 있어 **중복 예약**. 저재고 시연에서 유령 매진.
- **조치:** "다시 시도"(같은 키) 버튼 조건을 `LOCK_ACQUISITION_FAILED || REQUEST_IN_PROGRESS`로 확장하고 1순위 동선으로. 문구도 동작과 일치하게 수정.
- **처리:** 수정함

### [중요-4] countdown.ts 테스트 보강 (architecture — 일부 반박)

- **위치:** `frontend/lib/countdown.ts`
- **반박:** "65건 어디에도 포함 안 됨"은 사실과 다르다 — `computeRemainingSeconds` 테스트 4건이 `reservation-view.test.ts:52-70`에 있었다(오프셋 유무·과거·파싱 불가). 리뷰어가 파일명 기준으로만 찾은 것으로 보인다.
- **인정:** 다만 `Z` 접미 형식과 `formatMmSs`는 미검증이 맞고, 테스트가 남의 파일에 얹혀 있어 못 찾은 것 자체가 배치 문제다.
- **조치:** `countdown.test.ts`로 분리 신설, Z·formatMmSs 경계 케이스 추가.
- **처리:** 수정함 (반박 절에도 기록)

### [중요-5] mock 응답 본문이 컴파일 검증 밖 (architecture)

- **위치:** `frontend/lib/mock-backend.ts` (emptyReason 리터럴, reservationBody)
- **문제:** `json(status, body: unknown)`으로 들어가는 무타입 리터럴이라 `"SOLD_OUT"` 오타도 빌드 통과. 파일 스스로 "계약 상수만 내보낸다"고 선언하고 에러 코드에만 적용한 상태.
- **조치:** `reservationBody` 반환 타입을 `ReservationResponse`로, 검색 성공·빈 응답을 `AvailabilityResponse` 타입 값으로 조립해 컴파일 검증 안으로.
- **처리:** 수정함

### [중요-6] error-messages 매핑 키가 원시 문자열 — 오타·누락이 조용히 일반 오류로 샌다 (architecture)

- **위치:** `frontend/lib/error-messages.ts:14-43`
- **조치:** `contracts.ts`에서 `type ErrorCode = keyof typeof ERROR_CODES` 내보내고, `MESSAGES`를 계산된 키(`[ERROR_CODES.…]`) + `satisfies Record<ErrorCode, ScreenMessage>`로 — 계약 코드 추가·오타 시 컴파일 에러.
- **처리:** 수정함

### [중요-7] mock이 예약 생성의 날짜 창 하한을 검증하지 않는다 (domain)

- **위치:** `frontend/lib/mock-backend.ts:221-223`
- **문제:** `checkOut <= today` → 400(F01 D21), 판매 개시일 이전 → 재고 행 없음(409)이 mock에 없어, mock으로 개발한 화면이 실 백엔드(T6)에서 다르게 동작한다. 검색의 과거 checkIn도 F03은 400인데 mock은 NOT_YET_OPEN.
- **조치:** 생성에 하한 2종 추가, 검색 과거 날짜 400 추가, 테스트 동반.
- **처리:** 수정함

### [중요-8] mock 전이 기계의 전수 테스트 부재 (domain)

- **위치:** `frontend/lib/mock-backend.test.ts`
- **문제:** 스펙이 강조한 칸(EXPIRED+CANCEL=409, CONFIRMED+CANCEL 재고 복원, CANCELLED+CONFIRM=409)이 테스트에 없다. 현재 구현은 옳지만 if 분기라 회귀에 취약.
- **조치:** 도달 가능한 상태 × 이벤트 조합 테스트 추가 (check-in/check-out 경로 신설분 포함).
- **처리:** 수정함

## 제안 처리 (13건)

| 지적 | 리뷰어 | 처리 |
|---|---|---|
| UNKNOWN 리터럴 4곳 반복 → 상수화 + `messageForError` 헬퍼 | arch | 수정함 |
| `as` 단언 2곳 (currentTarget / isRecord 재사용) | arch | 수정함 |
| 시드·설정 지식 하드코딩 (판매 기간·정원·10분) | arch | **부분 수정** — "판매 중인 기간에서 찾기"는 응답의 `salesOpenUntil`로 계산하도록 수정. "10분"·"1실 4명" 문구는 미룸: 계약 기본값(PMS_RESERVATION_HOLD_MINUTES=10)·시드 고정값이며, Swagger 대조(T6) 때 응답 기반으로 바꿀 수 있는지 함께 확인 |
| 반응형 미디어쿼리 인라인 중복 → 공용 클래스 | arch | 수정함 (`.two-col`) |
| 상태 변화 aria-live/role 부재 | arch | 수정함 (최소: role="status"/"alert") |
| mock에 check-in/check-out 경로 없음 → CHECKED_IN·OUT 재현 불가 | domain | 수정함 (mock 경로 추가. 화면 버튼은 D8대로 계속 없음) |
| 만료 PENDING 복원이 조회 시점에만 → 검색 거짓 매진 | domain | 수정함 (검색 시 만료 스윕) |
| sold-out 후 "예약하기" 버튼 활성 | domain | 수정함 (비활성) |
| S1 매진 화면 "날짜 바꾸기" 버튼 누락 | domain | 수정함 |
| userId 변경이 멱등 키 수명에 미포함 | conc | 수정함 (userId 변경 시 키 재발급 — "다른 예약 시도 = 다른 키" 일관) |
| 카운트다운 0 → 재조회 1회 후 PENDING이면 00:00 영구 정지 | conc | 수정함 (재조회마다 Countdown 재시작 — key 부여) |
| mock 이중 복원 가드 회귀 테스트 없음 | conc | 수정함 (반복 GET+취소 후 잔여 총량 검증) |
| INVALID_STATE_TRANSITION 수렴이 무언 | conc | 수정함 (재조회 후 안내 배너, role="alert") |

## 반박

| 지적 | 반박 근거 |
|---|---|
| [중요-4] "countdown.ts는 65건 어디에도 테스트가 없다" | `computeRemainingSeconds` 테스트 4건이 `reservation-view.test.ts`에 이미 있었다 (오프셋 유무·과거 시각·파싱 불가). 다만 배치가 나빠 발견되지 않은 점, Z 형식·formatMmSs 미검증은 인정하고 보강했다 |
| (백엔드 함정 항목) | 세 리뷰어 모두 파이썬 백엔드 기준 재작성본이지만, 이번 결과에는 프론트에 안 맞는 지적이 없었다 — 반박할 백엔드 전용 항목 없음 |

## 다음 라운드로 넘긴 것

- "10분"·"1실 4명" 문구의 응답 기반화 — T6(Swagger 대조) 때 판단. 근거는 제안 처리 표 참조.
- 화면 컴포넌트 렌더링 테스트(“검사 안 됨” 영역) — 완료 보고서의 한계 절에 기재하고, 도입 여부는 관리자 판단에 올린다.
