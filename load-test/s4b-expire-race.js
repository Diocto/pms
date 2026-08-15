// S4-B. 상태 전이 경합 — 만료 × 확정
//
// 증명 명제 (다). 00 문서 UC-5가 만료-확정 경합을 명시적 관심사로 들고 있다.
//
// ---------------------------------------------------------------------------
// 왜 S4보다 위험한가
// ---------------------------------------------------------------------------
// S4의 취소·확정은 둘 다 사용자 요청이라 각자 자기 예약 하나만 건드린다.
// 반면 만료는 **배치**다. 한 번의 호출이 만료 대상 전부를 훑으며 상태를 바꾸고
// 재고를 복원한다. 그 배치가 도는 동안 개별 확정 요청이 같은 행을 건드린다.
//
// 여기서 깨지면 두 가지가 일어난다.
//   1. 확정된 예약이 만료 처리된다 -> 방은 팔렸는데 재고가 돌아온다
//   2. 한 예약의 재고가 두 번 복원된다 -> 없는 방을 팔게 된다
//
// 전이 표상 CONFIRMED에는 EXPIRE 전이가 없다(거부 23칸 중 하나).
// 확정에 성공한 예약이 EXPIRED로 끝나면 그 자체로 (다) 위반이다.
//
// 만료 트리거를 여러 번 부르는 이유:
//   한 번만 부르면 확정 요청과 겹칠 확률이 낮다. 반복해서 불러 배치가 도는
//   구간을 넓히고, 동시에 **배치 자체의 멱등성**(같은 예약을 두 번 만료시키지
//   않는가)도 함께 본다. expiredCount 합계가 최종 EXPIRED 건수보다 크면
//   같은 예약을 두 번 센 것이다.
//
// ---------------------------------------------------------------------------
// 전제 조건 — expiresAt
// ---------------------------------------------------------------------------
// 이 시나리오는 "곧 만료될 PENDING 예약"이 필요하다. 만료가 30분 뒤라면
// 부하테스트로 재현할 수 없다. 두 경로 중 하나가 필요하다.
//   (1) 앱 설정으로 만료 시간을 짧게(예: 5초) 만들 수 있다  <- 선호
//   (2) reset.sh가 DB의 expires_at을 직접 과거로 당긴다      <- 차선
// 어느 쪽인지는 미확정이다 (scenarios.md §8 Q10).
// EXPIRE_MODE=db 로 실행하면 (2)를 쓴다고 보고, seed 뒤에 안내만 출력한다.
//
// 설계: docs/load-test/scenarios.md §4 S4-B
// 실행 전: ./reset.sh s4b

import exec from 'k6/execution';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { PLAN, STATUS, RESPONSE_FIELDS, idField } from './config.js';
import { installResponseCallback, createReservation, confirm, triggerExpire } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

const TARGET = PLAN.s4b;
const ROOM_TYPE = TARGET.roomType;
const DATES = TARGET.dates;     // 100실 × 4일 = 400건 확보
const COUNT = 400;

// 만료 배치가 보고한 만료 건수의 총합.
// 최종 EXPIRED 행 수와 정확히 같아야 한다. 크면 이중 만료다.
const expiredReported = new Counter('expired_reported');
// 확정에 성공한(200 + CONFIRMED) 예약 수. 최종 CONFIRMED 수와 대조한다.
const confirmedOk = new Counter('confirm_succeeded');

export const options = {
    scenarios: {
        confirms: {
            executor: 'shared-iterations',
            vus: COUNT,
            iterations: COUNT,
            maxDuration: '120s',
            exec: 'confirmAxis',
        },
        expires: {
            // 배치가 도는 구간을 넓힌다. 200ms 간격 15회.
            executor: 'constant-arrival-rate',
            rate: 5,
            timeUnit: '1s',
            duration: '3s',
            preAllocatedVUs: 2,
            maxVUs: 4,
            exec: 'expireAxis',
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        'http_req_duration{op:confirm}': ['p(95)<1000'],
    },
};

export function setup() {
    installResponseCallback();

    const targets = [];
    for (let i = 0; i < COUNT; i++) {
        const owner = `user-5${String(i).padStart(3, '0')}`;
        const date = DATES[i % DATES.length];
        const { outcome } = createReservation(ROOM_TYPE, date, {
            userId: owner,
            idempotencyKey: `s4b-seed-${i}`,
            roomCount: 1,
        });
        if (outcome.kind === 'created') {
            targets.push({ ref: outcome.body[idField()], owner, date });
        }
    }

    console.log(`[S4-B] PENDING 예약 ${targets.length}건 준비 (목표 ${COUNT}건)`);
    if (__ENV.EXPIRE_MODE === 'db') {
        console.log('[S4-B] EXPIRE_MODE=db — 지금 reset.sh 가 expires_at 을 과거로 당겼는지 확인할 것.');
    } else {
        console.log('[S4-B] 앱의 만료 시간이 짧게 설정돼 있어야 한다. 아니면 만료가 0건으로 끝난다.');
    }
    return { targets };
}

export function confirmAxis(data) {
    const n = exec.scenario.iterationInTest;
    const target = data.targets[n];
    if (!target) return;

    const { res, outcome } = confirm(target.ref, { userId: target.owner });
    if (outcome.kind === 'ok' && outcome.status === STATUS.CONFIRMED) {
        confirmedOk.add(1);
    }

    check(res, {
        '5xx 아님': () => outcome.kind !== 'error',
        '404 아님': () => outcome.kind !== 'not_found',
        '성공이거나 금지 전이 거절': () =>
            ['ok', 'idempotent', 'declined', 'transition', 'lock_failed'].includes(outcome.kind),
        '확정 응답이 EXPIRED는 아님': () => outcome.status !== STATUS.EXPIRED,
    });
}

export function expireAxis() {
    const res = triggerExpire();
    let count = 0;
    try {
        count = res.json()[RESPONSE_FIELDS.expiredCount] || 0;
    } catch (e) {
        count = 0;
    }
    expiredReported.add(count);

    check(res, {
        '만료 배치가 5xx 아님': (r) => r.status < 500,
    });
}

export function teardown() {
    console.log('[S4-B] verify/s4b.sql 로 확인할 것.');
    console.log('[S4-B] 기대: CONFIRMED + EXPIRED = 400, PENDING 0건');
    console.log('[S4-B] 기대: expired_reported 합계 == 최종 EXPIRED 행 수. 크면 이중 만료다.');
    console.log('[S4-B] 기대: confirm_succeeded == 최종 CONFIRMED 행 수. 다르면 확정된 예약이 만료된 것이다.');
    console.log('[S4-B] 기대: 잔여 + CONFIRMED 건수 = 총 객실 수. 잔여가 총량을 넘으면 복원 과다다.');
}
