// S7. 프로모션 스파이크
//
// 증명 명제 (가)의 스파이크 판본. F02가 절단되면 이 시나리오는 폐기한다.
//
// S1이 "많이 몰림"이라면 S7은 "0에서 갑자기 최대치"다. 커넥션 풀과 스레드
// 풀이 예열 없이 얻어맞는다. 그래서 워밍업을 하지 않는다 — 예열 없이 맞는
// 것이 이 시나리오의 관심사다.
//
// ---------------------------------------------------------------------------
// F02의 1차 방어가 락이 아니라 Redis 카운터라는 점이 관측 포인트를 바꾼다
// ---------------------------------------------------------------------------
// 잔여 20에 8,000요청이 몰릴 때 분산락으로 직렬화하면, 이미 매진된 뒤에도
// 7,980개가 락을 순서대로 기다렸다가 DB를 한 번씩 두드린다. 락은 경합을
// 줄이는 게 아니라 줄 세우는 수단이다. 선착순에서 필요한 건 줄 세우기가
// 아니라 일찍 자르기고, F02는 Redis DECR로 그렇게 했다.
//
// 그래서 S7이 봐야 할 것은 성공 20건만이 아니다.
//   **매진 뒤 요청이 DB에 닿지 않는가** — 즉 초과 트래픽이 얼마나 빨리
//   잘리는가. 거절 응답의 지연이 성공 응답보다 확실히 짧아야 한다.
//   그게 카운터 게이트가 실제로 앞단에서 잘랐다는 증거다.
//
// 대상: P1 (id=1 스탠다드 100실, 2026-09-14, 특가 20실, 이미 열림)
//   일반 재고가 100실이라 특가 20을 빼도 80이 남는다. 일반 재고가 특가보다
//   빠듯하면 특가가 소진되기 전에 일반 재고가 먼저 바닥나, 재는 것이
//   "특가 선착순 정확성"이 아니라 "일반 재고 고갈"로 조용히 바뀐다.
//
// 설계: docs/load-test/scenarios.md §4 S7
// 실행 전: ./reset.sh s7

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import { BASE_URL, PROMOTIONS, ERROR_CODE, promotionPath, headers } from './config.js';
import { installResponseCallback } from './lib/api.js';
import { BASE_THRESHOLDS, M } from './lib/metrics.js';

const P = PROMOTIONS.p1;
const QUANTITY = P.quantity; // 20

// 성공과 거절의 지연을 따로 잰다. 거절이 훨씬 빨라야 게이트가 앞단에서
// 잘랐다는 뜻이다. 둘이 비슷하면 매진 요청도 DB까지 갔다는 뜻이다.
const okDuration = new Trend('promo_ok_duration');
const soldOutDuration = new Trend('promo_soldout_duration');
const promoCreated = new Counter('promo_created');
const promoSoldOut = new Counter('promo_sold_out');

export const options = {
    scenarios: {
        spike: {
            // 워밍업 없이 0에서 3초 만에 초당 500건까지 올린다.
            executor: 'ramping-arrival-rate',
            startRate: 0,
            timeUnit: '1s',
            preAllocatedVUs: 300,
            maxVUs: 600,
            stages: [
                { target: 500, duration: '3s' },
                { target: 500, duration: '15s' },
                { target: 0, duration: '2s' },
            ],
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        // 스파이크 특성상 완화한다. 대신 리포트에 분포를 싣는다.
        http_req_duration: ['p(95)<1500', 'p(99)<3000'],
        promo_created: [`count==${QUANTITY}`],
    },
};

export function setup() {
    installResponseCallback();
    console.log(`[S7] P1 특가: roomType=${P.roomType.id} date=${P.date} 수량=${QUANTITY}`);
    console.log(`[S7] 일반 재고 ${P.roomType.total}실. 특가를 빼도 ${P.roomType.total - QUANTITY}실이 남아 측정이 깨끗하다.`);
    return { date: P.date, roomTypeId: P.roomType.id };
}

export default function (data) {
    const n = exec.scenario.iterationInTest;
    // 특가 예약은 1실 고정이다 (F02 D4). 본문 없이 경로와 헤더로만 요청한다.
    const res = http.post(
        `${BASE_URL}${promotionPath(data.roomTypeId, data.date, 'reservations')}`,
        null,
        {
            headers: headers(`user-7${String(n % 9000).padStart(4, '0')}`, `s7-${exec.instance.idInTest}-${n}`),
            tags: { op: 'promo' },
        },
    );

    let code = null;
    try {
        code = res.json().code;
    } catch (e) { /* 성공 응답에는 code가 없다 */ }

    if (res.status === 201) {
        promoCreated.add(1);
        okDuration.add(res.timings.duration);
    } else if (res.status === 409 && code === ERROR_CODE.PROMOTION_SOLD_OUT) {
        promoSoldOut.add(1);
        soldOutDuration.add(res.timings.duration);
    } else if (res.status === 200) {
        // 멱등 재요청. 키가 요청마다 다르므로 여기 오면 안 된다.
        M.rsvReplayed.add(1);
    } else if (res.status === 409) {
        M.rejDuplicate.add(1);
    } else if (res.status === 400) {
        M.badRequest.add(1);
    } else if (res.status >= 500) {
        M.serverError.add(1);
    }

    check(res, {
        '5xx 아님': (r) => r.status < 500,
        '201 또는 409': (r) => r.status === 201 || r.status === 409,
    });
}

export function teardown() {
    console.log('[S7] verify/s7.sql 로 확인할 것.');
    console.log(`[S7] 기대: 특가 예약 정확히 ${QUANTITY}건, promotion_inventory.remaining = 0`);
    console.log('[S7] 기대: remaining 이 한 번도 음수가 아니었을 것 (CHECK 위반 로그가 없어야 한다)');
    console.log('[S7] 관측: promo_soldout_duration 이 promo_ok_duration 보다 확실히 짧아야 한다.');
    console.log('[S7]      비슷하다면 매진 뒤 요청도 DB까지 갔다는 뜻이고, 카운터 게이트가');
    console.log('[S7]      앞단에서 자르지 못했다는 신호다.');
    console.log('[S7] 일반 재고 판정은 Q7(차감 연동 여부) 확정 후 verify/s7.sql 에서 고른다.');
}
