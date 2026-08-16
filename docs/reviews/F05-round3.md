# [F05] 코드리뷰 라운드 3 (수정 검증 라운드)

- 날짜: 2026-08-16
- 대상 커밋: 010a7f9 (라운드2 반영분)
- 리뷰어: concurrency-reviewer / domain-reviewer / architecture-reviewer

## 요약

| 리뷰어 | 심각 | 중요 | 제안 | 판정 |
|---|---|---|---|---|
| concurrency-reviewer | 0 | 1 | 2 | 재작업 |
| domain-reviewer | 0 | 1 | 2 | 재작업 |
| architecture-reviewer | 0 | 0 | 3 | 통과 (vitest·tsc·build 직접 실행 확인) |

**종합 판정: 재작업 → 전 건 수정 완료** (이 문서 커밋에 포함). 수정 후 테스트 115건·tsc·build 통과.

## 중요 지적과 처리

### [중요-1] Countdown의 firedRef가 타이머 발화 전에 소진 — 클린업 한 번에 만료 재조회 영구 정지 (concurrency)

- **문제:** 라운드2의 폴링 지연 수정이 effect 재실행(StrictMode 기본인 dev, 또는 재렌더로 바뀌는 인라인 onExpired 의존성)과 결합하면, 예약만 걸린 타이머가 클린업으로 사라진 채 firedRef가 이미 참이라 재조회가 영영 발화하지 않는다. 라운드1의 "00:00 영구 정지"가 dev에서 100% 재현되는 형태로 재발.
- **처리: 수정함 (구조 변경)** — ① 발화 판정을 순수 함수 `expiryFireDelayMs`로 `lib/countdown.ts`에 추출하고 테스트 3건 추가. ② `onExpired`를 ref로 들어 effect 의존성을 `[left]`로 축소 — 재렌더로 인한 재실행 자체가 사라짐. ③ `firedRef`는 실제 발화 시점(타이머 콜백 안)에만 세움 — 예약과 발화 사이의 틈 제거.
- **기록:** 카운트다운 재조회 지점은 라운드 1(제안)→2(중요)→3(중요)로 세 라운드 연속 지적됐다. 원인은 컴포넌트에 박힌 타이밍 로직이 테스트 밖이었던 것 — 이번에 판정을 lib로 추출해 구조적으로 닫았다. dev-cycle의 "같은 지적 연속" 신호에 해당하므로 완료 보고서에 이 이력을 명시한다.

### [중요-2] SALES_CHECKOUT_LIMIT이 선언만 되고 비교 지점 2곳은 리터럴 그대로 — 라운드2 문서 기록과 불일치 (domain)

- **문제:** 라운드2에서 "수정함"으로 기록했으나 실제로는 상수 선언만 하고 사용처 교체를 빠뜨렸다. 수정 검증 라운드에서 기록 신뢰를 깨는 불일치.
- **처리: 수정함 + 문서 정정** — 비교 2곳을 상수로 교체하고, round2 문서의 해당 행을 "정정(라운드3에서 발각)"으로 고쳤다. `shiftDate` 중복도 `dates.addDays`로 통합.

## 라운드2 항목 검증 결과 (리뷰어 판정)

- 전이 24칸 전수 테스트: **고쳐짐** (F01 1.4와 전 칸 대조 일치, prepare 경로·EXPIRED 준비 유효성까지 확인)
- rebook 날짜 보정: **고쳐짐** (진행 중 투숙 → 결제 거절 → 재예약 흐름이 400으로 끝나지 않음을 추적 확인)
- 키 useState 단일화·userId 초기화: **고쳐짐** (StrictMode 이중 실행도 안전 판정)
- last-write-wins 순번 가드: **고쳐짐**
- api.test 타입 안전화·tsc 게이트·dates.ts 추출·typecheck 스크립트: **고쳐짐** (실행 확인)

## 제안 처리 (7건)

| 지적 | 리뷰어 | 처리 |
|---|---|---|
| runAction 오류 경로만 순번 가드 없음 | conc | 수정함 — catch에도 가드 |
| 주문서 진행 중 요청이 userId 전환 후 완주해 카드 부활 | conc | 수정함 — submit 순번 가드 (onPhase·결과·오류 전부) |
| rebook 날짜 탑재를 문구 문자열로 판정 + 클램프 미테스트 | domain | 수정함 — `rebookWithDates` 필드를 매핑 표로, `clampStayFrom`을 dates.ts로 추출·테스트 3건 |
| CONFIRMED+EXPIRE=거부 재현 테스트 부재 | domain | 수정함 — 확정 후 시계 전진 테스트 (재고 불변 포함) |
| contracts 파서의 검증-후-캐스트 2곳 | arch | 수정함 — `isEmptyReason`/`isReservationStatus` 타입 가드로, as 제거 |
| 24칸 테스트의 Object.entries 캐스트 | arch | 수정함 — 타입된 키 배열 이중 순회 |
| 날짜 산술 중복 (shiftDate·nights 식 2곳) | arch | 수정함 — dates.ts의 addDays·nightsBetween으로 통합 |

## 반박

없음.

## 다음 라운드로 넘긴 것

없음. 라운드 4는 이번 수정 2건(중요)의 확인 라운드로 진행한다.
