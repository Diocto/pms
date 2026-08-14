// S7. 프로모션 스파이크
//
// 증명 명제 (가)의 스파이크 판본. F02가 절단되면 이 시나리오는 폐기한다.
//
// S1이 "많이 몰림"이라면 S7은 "0에서 갑자기 최대치"다. 커넥션 풀과 스레드
// 풀이 예열 없이 얻어맞는다. 그래서 워밍업을 하지 않는다 — 예열 없이 맞는
// 것이 이 시나리오의 관심사다.
//
// ---------------------------------------------------------------------------
// 특가 예약은 별도 엔드포인트가 아니다
// ---------------------------------------------------------------------------
// 같은 POST /api/reservations 에 discounts 필드를 하나 더 실어 보낸다.
//   "discounts": [ { "type": "PROMOTION", "reference": "{promotionId}" } ]
// 0개 또는 1개다. 2개 이상이면 400.
//
// ---------------------------------------------------------------------------
// 소진되면 400이지 409가 아니다 — fail-closed
// ---------------------------------------------------------------------------
// 특가가 매진·만료됐거나 없으면 F01이 **400으로 거절한다. 정가로 조용히
// 넘어가지 않는다.** 돈이 걸린 판단이라 fail-closed로 설계했다.
// 조용히 정가로 넘어가면 사용자가 기대한 것보다 더 청구된다.
//
// 그래서 이 시나리오의 판정이 S1과 다르다.
//   - 성공(201)은 정확히 20건
//   - 나머지 약 7,980건은 **400**이다 (409 재고 부족이 아니다)
//   - **정가로 성공한 201이 하나라도 있으면 즉시 실패.** 응답의
//     pricePerNight가 75,000이 아니라 150,000인 건이 그것이다.
//     fail-closed가 뚫린 것이고, 사용자가 요청하지 않은 금액을 청구한 셈이다.
//   - **409 재고 부족이 섞여 나오면 측정 오염 신호다.** id=1이 100실이라
//     안 나와야 정상이고, 나오면 S7이 특가 경합이 아니라 일반 재고 경합을
//     재고 있다는 뜻이다.
//
// 대상: P1 (id=1 스탠다드 100실, 2026-09-14, 특가 20실, 이미 열림)
//   일반 재고가 100실이라 특가 20을 빼도 80이 남는다. 일반 재고가 특가보다
//   빠듯하면 특가가 소진되기 전에 일반 재고가 먼저 바닥나, 재는 것이
//   "특가 선착순 정확성"이 아니라 "일반 재고 고갈"로 조용히 바뀐다.
//
// 설계: docs/load-test/scenarios.md §4 S7
// 실행 전: ./reset.sh s7
//   PROMOTION_REF 를 F02 V202 시드의 실제 값으로 넘겨야 한다.

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import {
    BASE_URL, PATHS, PROMOTIONS, PROMOTION_REFERENCE,
    promotionDiscount, reservationBody, headers, userId,
} from './config.js';
import { installResponseCallback } from './lib/api.js';
import { BASE_THRESHOLDS, M } from './lib/metrics.js';

const P = PROMOTIONS.p1;
const QUANTITY = P.quantity;      // 20
const PROMO_PRICE = P.promoPrice; // 75000

// 성공과 거절의 지연을 따로 잰다.
//
// F02의 1차 방어는 분산락이 아니라 Redis 카운터다. 잔여 20에 8,000요청이
// 몰릴 때 락으로 직렬화하면 이미 매진된 뒤에도 7,980개가 락을 순서대로
// 기다렸다가 DB를 한 번씩 두드린다. 락은 경합을 줄이는 게 아니라 줄 세우는
// 수단이고, 선착순에서 필요한 건 줄 세우기가 아니라 일찍 자르기다.
//
// 그래서 **거절이 성공보다 확실히 빨라야 한다.** 비슷하면 매진 뒤 요청도
// DB까지 갔다는 뜻이고, 카운터 게이트가 앞단에서 자르지 못했다는 신호다.
const okDuration = new Trend('promo_ok_duration');
const rejectDuration = new Trend('promo_reject_duration');

const promoCreated = new Counter('promo_created');
const promoRejected = new Counter('promo_rejected');       // 400 (소진·만료)
// 정가로 성공했다. fail-closed가 뚫린 것이다.
const listPriceLeaked = new Counter('promo_list_price_leaked');
// 일반 재고 부족 409. 나오면 측정 대상이 바뀐 것이다.
const generalInventory409 = new Counter('promo_general_inventory_409');

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
        // 정가 청구는 한 건도 허용하지 않는다.
        promo_list_price_leaked: ['count==0'],
    },
};

export function setup() {
    installResponseCallback();
    console.log(`[S7] P1 특가: roomType=${P.roomType.id} date=${P.date} 수량=${QUANTITY} 단가=${PROMO_PRICE}`);
    console.log(`[S7] 일반 재고 ${P.roomType.total}실. 특가를 빼도 ${P.roomType.total - QUANTITY}실이 남아 측정이 깨끗하다.`);
    if (PROMOTION_REFERENCE.startsWith('TODO')) {
        console.warn('[S7] 경고: PROMOTION_REF 가 자리표시자다. F02 V202 시드의 실제 값을 넘겨라.');
    }
    return { date: P.date };
}

export default function (data) {
    const n = exec.scenario.iterationInTest;

    const body = reservationBody(P.roomType, data.date, {
        roomCount: 1,
        nights: 1,
        discounts: promotionDiscount(),
    });

    const res = http.post(`${BASE_URL}${PATHS.create}`, JSON.stringify(body), {
        headers: headers(userId(7000 + (n % 9000)), `s7-${exec.instance.idInTest}-${n}`),
        tags: { op: 'promo' },
    });

    let parsed = null;
    try { parsed = res.json(); } catch (e) { /* 본문 없음 */ }

    if (res.status === 201) {
        promoCreated.add(1);
        okDuration.add(res.timings.duration);
        // 특가로 요청했는데 정가가 청구됐다면 fail-closed가 뚫린 것이다.
        if (parsed && parsed.pricePerNight !== PROMO_PRICE) {
            listPriceLeaked.add(1);
            console.error(`[S7] 정가 청구 발견: pricePerNight=${parsed.pricePerNight} (기대 ${PROMO_PRICE})`);
        }
    } else if (res.status === 400) {
        // 특가 소진·만료. 이게 정상 거절이다.
        promoRejected.add(1);
        rejectDuration.add(res.timings.duration);
    } else if (res.status === 200) {
        // 멱등 재요청. 키가 요청마다 다르므로 여기 오면 안 된다.
        M.rsvReplayed.add(1);
    } else if (res.status === 409) {
        // 일반 재고 부족이면 측정 대상이 바뀐 것이다.
        const code = parsed && parsed.code;
        if (code === 'INSUFFICIENT_INVENTORY') {
            generalInventory409.add(1);
        } else {
            M.rejDuplicate.add(1);
        }
    } else if (res.status >= 500) {
        M.serverError.add(1);
    }

    check(res, {
        '5xx 아님': (r) => r.status < 500,
        '201 또는 400 (특가는 fail-closed다)': (r) => r.status === 201 || r.status === 400,
    });
}

export function teardown() {
    console.log('[S7] verify/s7.sql 로 확인할 것.');
    console.log(`[S7] 기대: 특가 예약 정확히 ${QUANTITY}건, promotion_inventory.remaining = 0`);
    console.log(`[S7] 기대: 특가 예약의 price_per_night 가 전부 ${PROMO_PRICE} (정가 ${P.listPrice}가 아님)`);
    console.log('[S7] 기대: promo_list_price_leaked = 0. 하나라도 있으면 fail-closed가 뚫린 것이다.');
    console.log('[S7] 관측: promo_reject_duration 이 promo_ok_duration 보다 확실히 짧아야 한다.');
    console.log('[S7]      비슷하다면 매진 뒤 요청도 DB까지 갔다는 뜻이다.');
    console.log('[S7] 경고: promo_general_inventory_409 > 0 이면 일반 재고가 먼저 바닥난 것이다.');
    console.log('[S7]      그러면 이 실행은 특가 경합이 아니라 일반 재고 고갈을 잰 것이므로 폐기한다.');
}
