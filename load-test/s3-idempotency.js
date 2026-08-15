// S3. 멱등성 폭주
//
// 증명 명제 (나): 같은 멱등성 키로 같은 요청을 여러 번 보내도 예약은 한 건만 생긴다.
//
// ---------------------------------------------------------------------------
// 이 시나리오에서 가장 틀리기 쉬운 지점
// ---------------------------------------------------------------------------
// 멱등 키는 (userId, idempotencyKey) **조합**으로 저장된다.
// 같은 키 문자열이라도 X-User-Id가 다르면 서로 다른 요청으로 취급된다.
//
// 그래서 재시도마다 VU 번호를 그대로 userId로 쓰면 키가 전혀 충돌하지 않고
// 요청이 전부 성공한다. 그러면 "중복 예약 0건"이라는 결론이 나오는데,
// 그건 멱등성이 작동해서가 아니라 **애초에 중복 요청을 보내지 않아서**다.
// 통과했지만 아무것도 증명하지 못한 실행이 된다.
//
// 그래서 키마다 전용 사용자를 묶는다. 키 i의 모든 재시도는 user-3xxx(i)를 쓴다.
// ---------------------------------------------------------------------------
//
// 재고는 넉넉한 타입(스탠다드 100실)을 쓴다. 재고 경합이 섞이면
// "예약이 한 건인 이유"가 멱등성 때문인지 재고 부족 때문인지 구분이 안 된다.
//
// 설계: docs/load-test/scenarios.md §4 S3
// 실행 전: ./reset.sh s3

import exec from 'k6/execution';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import { PLAN, idField } from './config.js';
import { installResponseCallback, createReservation } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

const TARGET = PLAN.s3;
const ROOM_TYPE = TARGET.roomType;
const DATE = TARGET.dates[0];

// MODE=a : 재시도 폭주   키 20개 × 50회 = 1,000건 -> 예약 20건
// MODE=b : 더블클릭     키 100개 × 2회 동시 = 200건 -> 예약 100건
const MODE = (__ENV.MODE || 'a').toLowerCase();
const KEYS = MODE === 'b' ? 100 : 20;
const REPEATS = MODE === 'b' ? 2 : 50;
const REQUESTS = KEYS * REPEATS;

// 같은 키에서 201이 두 번 나오면 그 순간 예약이 두 건 생긴 것이다.
// 뒤에 하나가 지워졌더라도 (나)는 이미 깨졌다. DB 행 수만 세면 놓친다.
const dupCreated = new Counter('idem_dup_created');
// 같은 키인데 서로 다른 확인번호를 돌려준 경우.
const codeMismatch = new Counter('idem_code_mismatch');
// 같은 키인데 금액이 달라진 경우 (재계산 버그).
const priceMismatch = new Counter('idem_price_mismatch');

export const options = {
    scenarios: {
        idempotency: {
            executor: 'shared-iterations',
            // MODE=b는 키마다 정확히 2개 VU가 동시에 쏘게 VU를 요청 수와 맞춘다.
            vus: MODE === 'b' ? REQUESTS : 100,
            iterations: REQUESTS,
            maxDuration: '120s',
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        http_req_duration: ['p(95)<500'],
        // 재고 경합이 없으므로 201은 정확히 키 개수여야 한다.
        rsv_created: [`count==${KEYS}`],
        idem_dup_created: ['count==0'],
        idem_code_mismatch: ['count==0'],
        idem_price_mismatch: ['count==0'],
    },
};

export function setup() {
    installResponseCallback();
    console.log(`[S3-${MODE.toUpperCase()}] keys=${KEYS} repeats=${REPEATS} requests=${REQUESTS}`);
    console.log(`[S3] roomType=${ROOM_TYPE.id} date=${DATE} 기대 예약 ${KEYS}건`);
    return { date: DATE, keys: KEYS };
}

export default function (data) {
    const n = exec.scenario.iterationInTest;
    const slot = n % KEYS; // 어느 키를 쓸 것인가

    // 키와 사용자를 한 쌍으로 묶는다. 이게 이 시나리오의 핵심이다.
    const key = `s3-${MODE}-key-${slot}`;
    const user = `user-3${String(slot).padStart(3, '0')}`;

    const { res, outcome } = createReservation(ROOM_TYPE, data.date, {
        userId: user,
        idempotencyKey: key,
        roomCount: 1,
    });

    // 201/200 양쪽 다 같은 예약을 가리켜야 한다.
    // 재요청에 200을 주면서 다른 확인번호를 주면 DB에는 한 건이어도
    // 클라이언트는 두 예약이 있다고 믿는다.
    if (outcome.kind === 'created' || outcome.kind === 'replayed') {
        const body = outcome.body || {};
        recordFirstSeen(slot, body, outcome.kind);
    }

    check(res, {
        '5xx 아님': () => outcome.kind !== 'error',
        '400 아님': () => outcome.kind !== 'bad_request',
        // 락 실패(503)도 정상 결과다 — 같은 키 폭주는 생성 락에서도 부딪힌다.
        // 503 확정(2026-08-15) 전에 쓰인 체크라 2026-08-16 S3 첫 실행에서
        // 26건이 빨갛게 떴다. 판정 게이트가 아니라 체크라 결과는 유효했다.
        '201 · 200 · 409 · 503 중 하나': () =>
            ['created', 'replayed', 'duplicate', 'lock_failed'].includes(outcome.kind),
    });
}

// VU마다 메모리가 분리되므로 전역 집계는 못 한다.
// 대신 커스텀 지표로 위반을 세고, 정확한 대조는 실행 후 DB와 요약본으로 한다.
const seen = {}; // 이 VU가 본 키별 첫 응답

function recordFirstSeen(slot, body, kind) {
    const code = body[idField()];
    const price = body.totalPrice;
    const prev = seen[slot];

    if (!prev) {
        seen[slot] = { code, price, created: kind === 'created' ? 1 : 0 };
        return;
    }
    if (kind === 'created') {
        // 이 VU가 같은 키로 201을 두 번 받았다면 명백한 중복 생성이다.
        prev.created += 1;
        if (prev.created > 1) dupCreated.add(1);
    }
    if (code && prev.code && code !== prev.code) codeMismatch.add(1);
    if (price != null && prev.price != null && price !== prev.price) priceMismatch.add(1);
}

// 마무리 재시도 (2026-08-16 첫 실행에서 배운 것).
//
// 폭주 단계에서 키 하나가 생성 0건으로 끝날 수 있다 — 그 키의 담당 요청이
// 재고 락 200ms 대기에서 번번이 503을 받는 사이, 같은 키의 나머지 요청은
// 전부 "처리 중"(409)으로 즉시 거절되고, 재시도 몫이 소진된다. 실측:
// 1,000건이 0.7초에 몰린 회차에서 20키 중 1키가 그렇게 비었다. 중복은 0건
// 이었으므로 정합성 문제가 아니라 **가용성을 내준 것**이고, 503의 계약은
// "잠시 뒤 그대로 다시 보내라"다. 그래서 실제 클라이언트처럼 간격을 두고
// 재시도하는 단계를 폭주 뒤에 둔다. 명제 (나)의 완전한 문장은 이것이다:
// "폭주 중 몇 번 거절될 수는 있어도, 재시도가 성사되는 순간까지 합쳐
//  예약은 키당 정확히 1건이다."
// 이 단계의 201도 rsv_created 로 집계되므로 count==KEYS 판정은 그대로다.
export function teardown(data) {
    for (let slot = 0; slot < data.keys; slot++) {
        const key = `s3-${MODE}-key-${slot}`;
        const user = `user-3${String(slot).padStart(3, '0')}`;
        let settled = false;
        for (let attempt = 0; attempt < 20 && !settled; attempt++) {
            const { outcome } = createReservation(ROOM_TYPE, data.date, {
                userId: user,
                idempotencyKey: key,
                roomCount: 1,
            });
            if (outcome.kind === 'created') {
                console.log(`[S3] 마무리 재시도로 생성됨: ${key} (폭주 단계에서 0건이었다)`);
                settled = true;
            } else if (outcome.kind === 'replayed') {
                settled = true; // 이미 생성돼 있었다 — 정상
            } else {
                sleep(0.2); // 503/처리중 — 간격을 두고 다시
            }
        }
        if (!settled) {
            // rsv_created count==KEYS 임계값이 이 상태를 잡아 회차를 실패시킨다.
            console.error(`[S3] 마무리 재시도 20회로도 미해결: ${key}`);
        }
    }
    console.log(`[S3] verify/s3.sql 로 확인할 것. 기대 예약 ${data.keys}건.`);
    console.log('[S3] 기대: 예약 행 수 = 키 개수, 멱등키 중복 0행, 재고 차감 = 키 개수');
    console.log('[S3] k6의 rsv_created 도 정확히 키 개수여야 한다. DB 행 수만 보면');
    console.log('[S3] "두 건 생겼다가 하나 지워진" 경우를 놓친다.');
}
