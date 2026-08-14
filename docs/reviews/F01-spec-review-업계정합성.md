# [F01] 스펙 검토: 도메인·ERD 업계 정합성

- 날짜: 2026-08-15
- 대상: docs/spec/F01-예약-코어.md 4·5절 (승인 전 스펙 검토. 코드리뷰 아님)
- 검토자: 서브에이전트 2 (업계 모델 비교 / 실무 시나리오 워크스루)
- 반영 여부: **대상 스펙 폐기됨** (2026-08-15 관리자 결정). 이 검토의 발견 사항은 F01 세션이 스펙을 새로 쓸 때 입력 자료로 쓴다. 폐기된 초안은 git 이력(spec-problem-and-scope 브랜치)에 남아 있다.

## 종합 판정

재고·동시성 코어는 업계 표준 모델과 일치한다. 날짜별 재고 행, 타입 판매 + 체크인 배정, CHECK 최후 방어선, 멱등 키, 가격 스냅샷, 백투백 재판매 처리 모두 표준 레퍼런스(ByteByteGo 호텔 예약 설계, OTA ARI 모델)와 같은 구조다. 괴리는 상업 레이어(요금제·인원·가격 구성)와 상태머신 구멍(NO_SHOW)에 몰려 있다.

## 발견 사항 (반영 후보 1~7)

| # | 발견 | 근거 | 제안 수정 | 안 고치면 |
|---|---|---|---|---|
| 1 | 인원수 필드 없음. `capacity`는 저장만 되고 안 읽히는 죽은 데이터 | 업계는 객실당 성인·아동 수가 필수 입력. 00문서 서사("인원으로 검색")와도 어긋남 | `reservation.guest_count` + UC-2 검증 `guest_count ≤ capacity × room_count` | 인원 없이 쌓인 행은 사후 복구 불가 |
| 2 | 타임존 미고정 | `created_at` DATETIME 무존, Clock 존 미지정. Testcontainers는 UTC, 로컬은 KST | "업무 시간 Asia/Seoul, Clock·DB 세션 존 고정" 스펙 한 줄 | 만료·당일 판정이 환경마다 9시간 어긋나는 플레이키 테스트 |
| 3 | CHECK 제약 3개 누락 | `room_count=-5`면 조건부 UPDATE가 재고를 늘림 (WHERE 통과). 이중 복원 버그는 remaining이 total을 초과해도 무감지 | V001에 `room_count>=1`, `check_out>check_in`, `remaining<=total_quantity` | 스스로 선언한 3층 방어의 최후선 구멍 |
| 4 | CONFIRMED 탈출 불가 경로 | 노쇼 시 나갈 전이 없음. CHECK_IN에 상한 없어 체크아웃 뒤에도 체크인 가능 | CHECK_IN 조건 `today < check_out` + NO_SHOW 상태·전이 (만료 스케줄러 패턴 재사용) | 상태머신 완결성 훼손. 과제의 간판 약점 |
| 5 | UC-3 보상 주장 과장 | 결제 성공 직후 크래시 시 결제 기록이 없어 보상 불가. 모의 결제라 실해 없음 | 크래시 틈 명시 + 실PG 시 결제 원장·정산 배치 필요성 기록 | 스펙 정직성 문제 |
| 6 | 1박 단가 스냅샷 없음 | F02 특가(날짜별 가격) 도입 후 total_price에서 밤별 단가 역산 불가 | `reservation.price_per_night` 컬럼 | 스냅샷은 사후 백필 불가 |
| 7 | auto-increment id가 공개 예약번호 | 예약량 추정·열거 가능. 업계는 불투명 확인번호 사용 | `confirmation_code`(무작위 UK) 응답 사용 | 나중에 바꾸면 API 파괴 |

## 문서화 후보 (00문서 제외 표에 추가)

업계에선 핵심이지만 이 과제에선 정당한 절단. 문서에 없다는 것만이 문제.

- 요금제(rate plan)와 날짜별 가격 제외. 단일 고정 단가
- 한 예약 = 한 객실타입. 다타입 묶음 예약 제외 (D6 주문서 자리가 확장 시임)
- 세금·수수료·통화 제외. 총액 단일 필드
- 확정 후 날짜·타입 변경 제외

## 명시적 보류 (검토자도 미룸 권고)

- 다타입 묶음의 주문 부모 테이블 (order/order-line 분리, 구조 변경 큼)
- NO_SHOW 이후 재판매 정책
- 멱등 키 재사용 시 페이로드 해시 검증 (동일 키 다른 내용 → 422)
- 90일 시드 밖 날짜의 "판매 전"과 "매진" 구분 (현재 둘 다 재고 부족 응답. fail-closed라 안전)

## 확인된 일치 (기록용)

일별 재고 행 = ARI 표준, 판매·배정 분리 = PMS 표준, CHECK 최후 방어선·멱등 UK = 표준 레퍼런스 동일, 기간 저장(예약) + 일 단위 행(재고) 이원화 = 표준, 백투백 체크아웃일 미점유 처리 정확.

출처: ByteByteGo Hotel Reservation System, Google Hotels ARI, Booking.com Connectivity API, Travelport Hotel Booking, Infor HMS·Oracle OPERA 상태 문서, Smart Order rate plan 가이드 (URL은 검토 원문 참조)
