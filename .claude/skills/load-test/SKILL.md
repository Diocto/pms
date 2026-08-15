---
name: load-test
description: k6 기반 부하테스트를 설계하고 실행하고 리포트를 만든다. 전체 개발이 끝난 뒤, 또는 특정 feature의 부하 검증이 필요할 때 사용한다.
---

# k6 부하테스트

부하테스트의 목적은 큰 숫자를 만드는 게 아니다. **말로 설계한 동시성·멱등성이 부하 아래서 실제로 지켜지는지 수치로 증명하는 것**이다.

## 절차

### 1. 부하 예측 포인트를 정한다

아무 API나 두드리지 않는다. **경합이 실제로 일어나는 지점**을 고른다.

| 포인트 | 왜 |
|---|---|
| 같은 객실·같은 날짜에 예약 집중 | 재고 차감 경합. 이 프로젝트의 심장 |
| 같은 멱등성 키로 재시도 폭주 | 중복 생성 방어 검증 |
| 프로모션 오픈 순간 | 특정 자원에 트래픽이 한 점으로 몰림 |
| 예약과 취소가 섞임 | 재고 복원과 차감의 경합 |
| 조회 폭주 속 예약 | 캐시와 실제 재고의 정합성 |

포인트마다 **검증할 불변식**을 먼저 쓴다. "재고 10개면 성공한 예약은 정확히 10건이고 잔여는 0이다"처럼 숫자로.

### 2. 시나리오를 설계한다

`docs/load-test/scenarios.md`에 설계를 쓴다. 시나리오마다 아래를 정한다.

- 부하 모델: 동시 사용자 수(VU) 또는 초당 요청 수(RPS), ramp-up 곡선
- 지속 시간
- 검증할 불변식
- 성공 기준: p95 지연, 에러율, **그리고 불변식**

**프로모션 시나리오는 스파이크 모델로 만든다.** 서서히 올리는 게 아니라 한순간에 꽂는다. `k6`의 `ramping-arrival-rate`로 0에서 목표 RPS까지 몇 초 안에 올린다.

### 3. 스크립트를 쓴다

`load-test/` 디렉터리에 시나리오별 `.js` 파일을 둔다.

```javascript
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

// 불변식 검증에 쓸 커스텀 지표
const reservationCreated = new Counter('reservation_created');
const inventoryRejected = new Counter('inventory_rejected');

export const options = {
    scenarios: {
        promotion_spike: {
            executor: 'ramping-arrival-rate',
            startRate: 0,
            timeUnit: '1s',
            preAllocatedVUs: 200,
            stages: [
                { target: 200, duration: '5s' },   // 5초 만에 초당 200건
                { target: 200, duration: '30s' },
                { target: 0, duration: '5s' },
            ],
        },
    },
    thresholds: {
        http_req_duration: ['p(95)<500'],
        http_req_failed: ['rate<0.01'],   // 5xx만 실패. 재고 부족 409는 정상 응답이다
    },
};
```

**주의할 것들**

- 409(재고 부족, 중복 요청)는 실패가 아니다. **의도된 거절**이다. `http_req_failed` 계산에서 빠지도록 `check`로 구분해 센다
- 사용자·멱등성 키를 시나리오 의도에 맞게 만든다. 멱등성 시나리오는 일부러 같은 키를 쓰고, 경합 시나리오는 서로 다른 키로 같은 자원을 노린다
- 테스트 전에 데이터를 초기화하는 스크립트를 같이 둔다. 이전 실행의 잔여 데이터가 섞이면 불변식 검증이 무의미하다

### 4. 실행한다

```bash
docker compose up -d
uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1 &
# 워커는 반드시 1이다. 여럿이면 프로세스마다 카운터를 따로 세서
# 합산 안 된 값이 조용히 진짜처럼 나간다. /api/internal/config의
# processId를 두 번 찍어 같은지 확인한다
k6 run load-test/<시나리오>.js --summary-export=docs/load-test/results/<시나리오>-summary.json
```

같은 머신에서 앱과 k6를 함께 돌리면 서로 자원을 뺏는다. **리포트에 이 한계를 명시한다.**

### 5. 불변식을 DB에서 직접 검증한다

k6 결과만 보고 끝내지 않는다. 부하가 끝난 뒤 **DB를 직접 조회해서** 확인한다.

```sql
-- 성공 응답 수와 실제 예약 행 수가 같은가
SELECT COUNT(*) FROM reservation WHERE status = 'CONFIRMED' AND ...;
-- 재고가 음수가 된 행이 있는가 (있으면 실패다)
SELECT * FROM room_daily_inventory WHERE remaining < 0;
```

**k6가 받은 성공 응답 수 = DB의 예약 행 수 = 초기 재고 수.** 이 등식이 리포트의 핵심 문장이다.

### 6. 리포트를 쓴다

`docs/load-test/report.md`에 쓴다.

- 환경: 머신 사양, 같은 머신에서 돌렸는지, 커넥션 풀 등 관련 설정값
- 시나리오별 결과: RPS, p50/p95/p99, 에러율
- **불변식 검증 결과: 기대값과 DB 실측값**
- 병목 분석: 무엇이 한계였나. 커넥션 풀인지 락 대기인지 CPU인지. 로그와 지표로 근거를 댄다
- 발견한 문제와 조치: 부하테스트로 찾은 버그가 있으면 그게 리포트의 하이라이트다

숫자를 나열하지 말고 **해석을 쓴다.** "p95가 480ms였다"가 아니라 "p95 480ms 중 대부분이 락 대기였다. 락 획득 실패 로그가 초당 N건 발생했고, 이는 설계대로 2차 방어선이 흡수했다"로 쓴다.

## 완료 기준

- [ ] 모든 시나리오에서 불변식이 지켜졌다 (재고 초과 0건, 중복 예약 0건)
- [ ] DB 실측으로 검증했다
- [ ] 병목을 근거와 함께 설명했다
- [ ] 리포트가 `docs/load-test/report.md`에 있다
