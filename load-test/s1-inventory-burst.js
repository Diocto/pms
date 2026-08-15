// S1. 재고 경합 — 순간 집중
//
// 증명 명제 (가): 잔여 N실에 N보다 훨씬 많은 동시 요청이 몰려도
//                성공 건수는 정확히 N이고 재고는 절대 음수가 되지 않는다.
//
// 대상: 스위트(id=3, 10실). F01 시드에서 재고가 가장 적은 타입이라
//       경합 배율 20배를 만들기에 정확히 맞는다. 재고를 손으로 줄이지 않으므로
//       보존식(remaining + 점유 = total_quantity)이 그대로 성립한다.
//
// 설계: docs/load-test/scenarios.md §4 S1
// 실행 전: ./reset.sh s1
// 실행 후: verify/s1.sql 로 DB를 직접 확인한다. k6 결과만으로 끝내지 않는다.

import exec from 'k6/execution';
import { check } from 'k6';
import { PLAN, userId } from './config.js';
import { installResponseCallback, createReservation } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

const TARGET = PLAN.s1;
const ROOM_TYPE = TARGET.roomType;
const DATE = TARGET.dates[0];
const STOCK = ROOM_TYPE.total; // 10
const REQUESTS = 200;          // 재고의 20배

export const options = {
    scenarios: {
        burst: {
            // VU 200이 각각 1회만 쏜다. 요청 수를 늘리는 것보다
            // 도달 시점을 겹치는 게 이 시나리오의 목적이다.
            executor: 'shared-iterations',
            vus: REQUESTS,
            iterations: REQUESTS,
            maxDuration: '60s',
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        http_req_duration: ['p(95)<1000'],
        // 성공은 정확히 재고 수. 이게 이 시나리오의 결론이다.
        rsv_created: [`count==${STOCK}`],
    },
};

export function setup() {
    installResponseCallback();
    console.log(`[S1] roomType=${ROOM_TYPE.id} date=${DATE} stock=${STOCK} requests=${REQUESTS}`);
    return { date: DATE, stock: STOCK };
}

export default function (data) {
    const n = exec.scenario.iterationInTest;
    const { res, outcome } = createReservation(ROOM_TYPE, data.date, {
        userId: userId(n),
        // 요청마다 다른 키. 멱등성이 아니라 재고 경합을 보는 시나리오다.
        idempotencyKey: `s1-${exec.instance.idInTest}-${n}`,
        roomCount: 1,
    });

    check(res, {
        '5xx 아님': () => outcome.kind !== 'error',
        '400 아님 (요청은 항상 유효해야 한다)': () => outcome.kind !== 'bad_request',
        '성공이거나 정중한 거절': () =>
            outcome.kind === 'created' ||
            outcome.kind === 'inventory' ||
            outcome.kind === 'lock_failed',
    });
}

export function teardown(data) {
    // k6는 여기서 끝나지만 판정은 끝나지 않는다.
    console.log(`[S1] 초기 재고 ${data.stock}. 이제 verify/s1.sql 로 DB를 확인할 것.`);
    console.log(`[S1] 기대: 활성 예약 ${data.stock}건, 잔여 0, remaining<0 인 행 0건, 보존식 = ${data.stock}`);
}
