# load-test — k6 부하테스트 스크립트

설계 문서는 `docs/load-test/scenarios.md`다. **이 디렉터리는 그 설계의 구현이며, 판정 기준의 진실은 설계 문서에 있다.**

## 구조

```
load-test/
├── config.js              모든 상수. API 계약이 바뀌면 여기만 고친다
├── lib/
│   ├── api.js             API 호출 래퍼. URL을 직접 만드는 곳은 여기뿐이다
│   └── metrics.js         공통 지표와 응답 분류
├── reset.sh               실행 전 초기화. 매번 돌린다
├── verify/*.sql           실행 후 DB 검증. k6 결과만으로 끝내지 않는다
└── s*.js                  시나리오별 부하 스크립트
```

## 왜 config.js에 전부 몰아넣었는가

F01의 결정 셋이 아직 관리자 승인 전이고, 기각되면 계약이 바뀐다.

| 결정 | 기각되면 | 대응 |
|---|---|---|
| D7 `confirmationCode` | 경로가 `/{code}` → `/{id}` 정수로 | `CODE_BASED_PATH=false` |
| D1 `guestCount` | 요청 본문에서 필드 제거 | `SEND_GUEST_COUNT=false` |
| D4 `NO_SHOW` | 상태 하나가 사라짐 (**절단 1순위**) | `NO_SHOW_ENABLED=false` |

시나리오 스크립트는 URL을 직접 만들지 않고 `pathFor()`만 쓴다. 그래서 계약이 뒤집혀도 고칠 곳이 한 파일이다.

## 실행 순서

```bash
docker compose up -d
./gradlew bootRun          # 또는 bootJar 후 java -jar

cd load-test
./reset.sh s1
k6 run s1-inventory-burst.js --summary-export=../docs/load-test/results/s1-summary.json
mysql -h127.0.0.1 -upms -ppms pms < verify/s1.sql
```

**세 단계가 다 끝나야 한 시나리오가 끝난 것이다.** `reset.sh`를 빼먹으면 이전 실행 데이터가 섞여 판정이 무의미해지고, `verify/*.sql`을 빼먹으면 k6가 받은 응답만 보고 DB 실제 상태를 안 본 것이 된다.

## 필수 시나리오 (F01만 병합되면 전부 실행 가능)

| 스크립트 | 증명하는 것 |
|---|---|
| `s1-inventory-burst.js` | 재고 10에 200요청 → 성공 정확히 10 |
| `s1c-partial-depletion.js` | 1·2·3실 혼합에서도 재고가 음수가 안 된다 |
| `s2-inventory-sustained.js` | 지속 부하에서 재고 100 → 성공 정확히 100 |
| `s3-idempotency.js` | 같은 키 반복에도 예약은 키 개수만큼만 |
| `s4-transition-race.js` | 취소·확정 동시 도착에서 금지 전이 0건 |
| `s4b-expire-race.js` | 만료 배치와 확정이 겹쳐도 이중 복원 0건 |
| `s6-mixed-soak.js` | 5분간 섞어 돌려도 재고 누수 0건 |

`s2`는 `TARGET=s5on` / `TARGET=s5off`로 S5(락 대조)에도 그대로 쓴다. **같은 부하를 넣었다고 말하려면 정말로 같은 코드여야 하기 때문이다.**

## 밟기 쉬운 함정 셋

**1. 같은 예약은 같은 `X-User-Id`로.** 취소가 소유자를 검증하는데 남의 예약이면 403이 아니라 **404**를 준다. VU 번호가 요청마다 바뀌면 전이 요청이 전부 404로 떨어지는데, 404는 "예약이 없다"로 읽혀서 원인을 찾는 데 한참 걸린다. `not_found` 지표를 하드 게이트로 둔 이유다.

**2. 멱등 키는 `(userId, key)` 조합이다.** 같은 키 문자열이라도 사용자가 다르면 별개 요청으로 취급된다. 재시도마다 VU가 바뀌면 키가 충돌하지 않아 전부 성공하고, "중복 0건"이라는 결론이 나온다. 멱등성이 작동해서가 아니라 **애초에 중복 요청을 안 보내서**다. `s3`는 키마다 전용 사용자를 묶는다.

**3. 결제 거절은 200이다.** `confirm`은 결제가 거절돼도 HTTP 200을 주고 본문 `status`가 `CANCELLED`가 된다. HTTP 코드만 보고 성공을 세면 확정 성공률이 부풀려진다. `classifyTransition`이 본문까지 읽는 이유다.

## 응답 코드를 세는 규칙

거절은 에러가 아니다. 409(재고 소진·중복·금지 전이)는 시스템이 옳게 동작한 증거이므로 에러율에서 뺀다. 반면 503(락 획득 실패)은 재고가 남았는데도 예약을 못 해준 것이라 실패로 센다. 이건 **락 설계의 가격**이고, S5에서 락 없는 쪽과 비교할 대상이 바로 이 값이다.

`server_error` · `bad_request` · `not_found`는 셋 다 하드 게이트다. 0이 아니면 성능 미달이 아니라 **무효 실행**이므로 결과를 폐기하고 원인을 고쳐 다시 돌린다.
