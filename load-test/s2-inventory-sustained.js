// S2. 재고 경합 — 지속 부하   /   S5. 락 유무 대조의 부하 원본
//
// 증명 명제 (가). 그리고 S5가 이 스크립트를 그대로 재사용한다.
//
// S5가 별도 스크립트가 아닌 이유:
//   "같은 부하를 넣었다"고 말하려면 정말로 같은 코드여야 한다. 락 ON/OFF는
//   앱 설정(pms.lock.enabled)으로 바뀌므로 부하 스크립트는 손댈 필요가 없다.
//   날짜만 갈아 끼운다.
//
// 도착률 고정(constant-arrival-rate)을 쓰는 이유:
//   VU 고정 모델은 앱이 느려지면 요청 수도 같이 줄어, 느려진 사실이 지표에서
//   사라진다. 도착률을 고정해야 앱이 못 따라오는 만큼 지연이 드러난다.
//   S5 대조의 전제가 "두 조건에 같은 부하"이므로 이 모델이어야 한다.
//
// 대상: 스탠다드(id=1, 100실).
//
// 설계: docs/load-test/scenarios.md §4 S2, S5
//
// 실행:
//   ./reset.sh s2    && k6 run s2-inventory-sustained.js
//   ./reset.sh s5on  && TARGET=s5on  k6 run s2-inventory-sustained.js   # 앱은 락 ON으로 기동
//   ./reset.sh s5off && TARGET=s5off k6 run s2-inventory-sustained.js   # 앱은 락 OFF로 기동

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { BASE_URL, PATHS, PLAN, userId } from './config.js';
import { installResponseCallback, createReservation } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

const TARGET = PLAN[__ENV.TARGET || 's2'];
const ROOM_TYPE = TARGET.roomType;
const DATE = TARGET.dates[0];
const STOCK = ROOM_TYPE.total; // 100
const RATE = Number(__ENV.RATE || 300);
const DURATION = __ENV.DURATION || '20s';

export const options = {
    scenarios: {
        // 워밍업. 상태를 바꾸지 않는 경로만 두드려 JIT와 커넥션 풀을 예열한다.
        // 예약을 만들면 본 부하의 재고가 줄어 판정이 깨진다 (§3-5).
        warmup: {
            executor: 'constant-arrival-rate',
            rate: 50,
            timeUnit: '1s',
            duration: '30s',
            preAllocatedVUs: 50,
            maxVUs: 100,
            exec: 'warmup',
            tags: { phase: 'warmup' },
        },
        sustained: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: DURATION,
            preAllocatedVUs: 200,
            maxVUs: 400,
            startTime: '32s', // 워밍업이 끝난 뒤 시작
            tags: { phase: 'main' },
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        // 워밍업 구간은 집계에서 뺀다.
        'http_req_duration{phase:main}': ['p(95)<800', 'p(99)<2000'],
        rsv_created: [`count==${STOCK}`],
    },
};

export function setup() {
    installResponseCallback();
    console.log(`[S2/S5] roomType=${ROOM_TYPE.id} date=${DATE} stock=${STOCK} load=${RATE}/s x ${DURATION}`);
    return { date: DATE, stock: STOCK };
}

// health는 DB·Redis 커넥션까지 건드리므로 예열 대상으로 적절하다.
export function warmup() {
    http.get(`${BASE_URL}${PATHS.health}`, { tags: { op: 'warmup' } });
}

export default function (data) {
    const n = exec.scenario.iterationInTest;
    const { res, outcome } = createReservation(ROOM_TYPE, data.date, {
        userId: userId(n),
        idempotencyKey: `s2-${data.date}-${exec.instance.idInTest}-${n}`,
        roomCount: 1,
    });

    check(res, {
        '5xx 아님': () => outcome.kind !== 'error',
        '400 아님': () => outcome.kind !== 'bad_request',
        '성공이거나 정중한 거절': () =>
            outcome.kind === 'created' ||
            outcome.kind === 'inventory' ||
            outcome.kind === 'lock_failed',
    });
}

export function teardown(data) {
    console.log(`[S2/S5] 날짜 ${data.date}, 초기 재고 ${data.stock}.`);
    console.log('[S2/S5] verify/s2.sql 로 확인: 활성 예약 = 재고, 잔여 = 0, remaining<0 0건');
    console.log('[S5 대조] 락 OFF에서도 성공이 정확히 재고 수여야 한다. 2차 방어선(조건부 UPDATE)의 증명이다.');
    console.log('[S5 대조] 초과 판매가 나오면 F04의 실패가 아니라 발견이다. 즉시 보고할 것.');
}
