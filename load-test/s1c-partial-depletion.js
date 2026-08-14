// S1-C. 재고 경합 — 부분 소진 (roomCount 혼합)
//
// 증명 명제 (가)의 어려운 판본.
//
// 왜 S1보다 어려운가:
//   1실씩 빠지면 마지막 한 칸에서만 경계 판단이 필요하다. 그런데 요청 실수가
//   섞이면 "잔여 2에 3실 요청은 거절, 2실 요청은 통과"를 원자적으로 판단해야
//   한다. 조건이 remaining > 0 이 아니라 remaining >= :n 이어야 하고,
//   여기가 틀리면 재고가 -1로 내려간다.
//
//   그리고 최종 잔여가 0이 아닐 수 있다. 잔여 2에 3실 요청만 남으면 2가 남은 채
//   끝난다. 그래서 "잔여 == 0"으로 판정할 수 없고 보존식으로만 판정한다.
//
// 설계: docs/load-test/scenarios.md §4 S1-C
// 실행 전: ./reset.sh s1c

import exec from 'k6/execution';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { PLAN, userId } from './config.js';
import { installResponseCallback, createReservation } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

// 오션뷰 스위트(id=5, 20실, capacity=4). 3실 요청까지 정원이 여유롭다.
const TARGET = PLAN.s1c;
const ROOM_TYPE = TARGET.roomType;
const DATE = TARGET.dates[0];
const STOCK = ROOM_TYPE.total; // 20
const REQUESTS = 300;          // 1·2·3실 각 100건 = 요청 실수 합 600 (재고의 30배)

// 성공한 요청들의 roomCount 합. DB의 room_count 합과 일치해야 한다.
const roomsSold = new Counter('rooms_sold');

export const options = {
    scenarios: {
        mixed: {
            executor: 'shared-iterations',
            vus: REQUESTS,
            iterations: REQUESTS,
            maxDuration: '60s',
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        http_req_duration: ['p(95)<1000'],
        // 팔린 방이 재고를 넘으면 초과 판매다. 이게 주 표적이다.
        rooms_sold: [`value<=${STOCK}`],
    },
};

export function setup() {
    installResponseCallback();
    console.log(`[S1-C] roomType=${ROOM_TYPE.id} date=${DATE} stock=${STOCK} requests=${REQUESTS}`);
    return { date: DATE, stock: STOCK };
}

export default function (data) {
    const n = exec.scenario.iterationInTest;
    // 1·2·3실을 균등 혼합한다. guestCount는 config가 정원 안쪽으로 계산한다.
    const roomCount = (n % 3) + 1;

    const { res, outcome } = createReservation(ROOM_TYPE, data.date, {
        userId: userId(n),
        idempotencyKey: `s1c-${exec.instance.idInTest}-${n}`,
        roomCount,
    });

    if (outcome.kind === 'created') {
        roomsSold.add(roomCount);
    }

    check(res, {
        '5xx 아님': () => outcome.kind !== 'error',
        '400 아님': () => outcome.kind !== 'bad_request',
        '성공이거나 재고 부족 거절': () =>
            outcome.kind === 'created' ||
            outcome.kind === 'inventory' ||
            outcome.kind === 'lock_failed',
    });
}

export function teardown(data) {
    console.log(`[S1-C] 초기 재고 ${data.stock}. verify/s1c.sql 로 DB를 확인할 것.`);
    console.log(`[S1-C] 기대: remaining<0 인 행 0건, 보존식 = ${data.stock}, 최종 잔여 0~2`);
    console.log('[S1-C] 기대값은 0이다. 1실 요청이 100건이나 남아 있어 마지막 한 칸까지 채워지는 것이 정상이다.');
    console.log('[S1-C] 잔여가 3 이상이면 들어갈 자리가 있는데 거절된 것 — 초과 판매의 반대편 오류다.');
    console.log('[S1-C] k6의 rooms_sold 와 DB의 room_count 합이 같아야 한다.');
}
