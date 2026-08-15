// S4. 상태 전이 경합 — 취소 × 확정
//
// 증명 명제 (다): 전이 표에 없는 상태 전이는 동시 요청 상황에서도 통과하지 않는다.
//
// ---------------------------------------------------------------------------
// 판정이 단순하지 않다는 점을 먼저 이해할 것
// ---------------------------------------------------------------------------
// PENDING에서 CONFIRM과 CANCEL은 둘 다 전이 표 안에 있다. CONFIRMED에서
// CANCEL도 표 안에 있다. 그래서 "둘 다 성공했다"가 곧 위반은 아니다.
// CONFIRM 먼저, CANCEL 나중이면 표를 두 번 정상적으로 탄 것이다.
//
// 진짜 위반은 이것들이다.
//   - CANCEL이 2xx를 받았는데 최종 상태가 CONFIRMED
//   - CANCEL 성공 이후 도착한 CONFIRM이 2xx (CANCELLED는 종료 상태다)
//   - 최종 상태가 PENDING (둘 다 먹히지 않았다)
//   - 상태와 재고가 안 맞는다
//
// 그리고 결제 거절이 섞인다. confirm은 결제가 거절돼도 HTTP 200을 주고
// 본문 status가 CANCELLED가 된다. **HTTP 코드가 아니라 본문 status로
// 분류해야 한다.** classifyTransition이 이 구분을 담당한다.
//
// ---------------------------------------------------------------------------
// 소유자 함정
// ---------------------------------------------------------------------------
// 취소는 소유자를 검증하고, 남의 예약이면 403이 아니라 404를 준다.
// 그래서 한 예약의 confirm·cancel은 반드시 **그 예약을 만든 userId**로
// 보내야 한다. VU 번호를 그대로 쓰면 전부 404로 떨어지는데, 404는
// "예약이 없다"로 읽혀서 원인을 찾는 데 한참 걸린다.
// setup()이 (code, owner) 쌍을 만들어 넘기고, VU는 그 owner를 그대로 쓴다.
//
// 설계: docs/load-test/scenarios.md §4 S4
// 실행 전: ./reset.sh s4

import exec from 'k6/execution';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { PLAN, STATUS, idField, userId } from './config.js';
import { installResponseCallback, createReservation, confirm, cancel } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

const TARGET = PLAN.s4;
const ROOM_TYPE = TARGET.roomType;
const DATES = TARGET.dates;      // 100실 × 3일 = 300건 확보
const PAIRS = 300;
const REQUESTS = PAIRS * 2;

// 두 요청이 실제로 겹쳤다는 증거. 0이면 "완벽하다"가 아니라
// "경합이 일어나지 않았다"이므로 시나리오를 의심해야 한다.
const raceObserved = new Counter('race_observed');

export const options = {
    scenarios: {
        race: {
            executor: 'shared-iterations',
            vus: REQUESTS,      // 쌍의 두 요청이 서로 다른 VU에서 동시에 나간다
            iterations: REQUESTS,
            maxDuration: '120s',
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        http_req_duration: ['p(95)<800'],
        // 경합이 실제로 일어났는가. 증거 없이 "경합에 안전하다"고 쓸 수 없다.
        race_observed: ['count>=1'],
    },
};

export function setup() {
    installResponseCallback();

    // PENDING 예약 300건을 미리 만든다. 재고는 100실 × 3일로 확보한다.
    const targets = [];
    for (let i = 0; i < PAIRS; i++) {
        const owner = `user-4${String(i).padStart(3, '0')}`;
        const date = DATES[i % DATES.length];
        const { outcome } = createReservation(ROOM_TYPE, date, {
            userId: owner,
            idempotencyKey: `s4-seed-${i}`,
            roomCount: 1,
        });
        if (outcome.kind === 'created') {
            targets.push({ ref: outcome.body[idField()], owner, date });
        }
    }

    console.log(`[S4] PENDING 예약 ${targets.length}건 준비 (목표 ${PAIRS}건)`);
    if (targets.length < PAIRS) {
        console.warn('[S4] 준비된 예약이 목표보다 적다. 재고나 날짜 배정을 확인할 것.');
    }
    return { targets };
}

export default function (data) {
    const n = exec.scenario.iterationInTest;
    const pair = Math.floor(n / 2);
    const target = data.targets[pair];
    if (!target) return;

    // 짝수 iteration은 확정, 홀수는 취소. 같은 예약에 동시에 도달한다.
    const isConfirm = n % 2 === 0;
    const call = isConfirm ? confirm : cancel;

    // 반드시 예약을 만든 사용자로 보낸다. 아니면 404가 온다.
    const { res, outcome } = call(target.ref, { userId: target.owner });

    // 상대가 이미 먹어서 거절당했다면 두 요청이 실제로 겹친 것이다.
    if (outcome.kind === 'transition') {
        raceObserved.add(1);
    }

    check(res, {
        '5xx 아님': () => outcome.kind !== 'error',
        '404 아님 (소유자를 제대로 물렸는가)': () => outcome.kind !== 'not_found',
        '성공이거나 금지 전이 거절': () =>
            ['ok', 'idempotent', 'declined', 'transition', 'lock_failed'].includes(outcome.kind),
        '최종 상태가 PENDING이 아님': () =>
            outcome.status !== STATUS.PENDING,
    });
}

export function teardown() {
    console.log('[S4] verify/s4.sql 로 확인할 것.');
    console.log('[S4] 기대: CONFIRMED + CANCELLED = 300, PENDING 0건, 그 외 상태 0건');
    console.log('[S4] 기대: 잔여 = (총 객실 수 - CONFIRMED 건수). 상태와 재고가 짝이 맞아야 한다.');
    console.log('[S4] race_observed 가 0이면 경합이 안 일어난 것이다. 통과가 아니라 재실행 대상이다.');
}
