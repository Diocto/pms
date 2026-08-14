// L5. 캐시 스탬피드 관찰
//
// **합격·불합격이 없는 시나리오다.** F03이 스탬피드 방어 도입 여부를
// "측정 후 판단"으로 미뤘고(스펙 D10), 그 판단 근거를 만드는 것이 목적이다.
// F04는 측정만 하고 결론을 대신 내리지 않는다.
//
// ---------------------------------------------------------------------------
// 무엇을 보는가
// ---------------------------------------------------------------------------
// 인기 검색 조건의 캐시가 TTL로 만료되는 순간, 그 조건을 조회하던 수백
// 요청이 동시에 캐시 미스를 맞고 전부 DB로 몰려간다. 캐시가 있어서 조용하던
// DB에 10초마다 한 번씩 파도가 친다.
//
// 방어(하나만 DB에 보내고 나머지는 그 결과를 기다림)를 넣을 값어치가 있는지는
// 그 파도가 실제로 얼마나 큰지 재봐야 안다.
//   - 만료 순간 DB 조회가 한 자릿수  -> 방어 불필요
//   - 수십 ~ 수백                    -> 방어를 넣을 근거
//
// 그래서 **캐시 키를 딱 하나로 고정한다.** 모든 요청이 같은 조건을 조회해야
// 만료 순간이 한 점에 모인다. 조건이 흩어지면 만료도 흩어져서 파도가 안 보인다.
//
// 설계: docs/load-test/scenarios.md §4 L5
// 실행 전: ./reset.sh s8   (S8과 날짜 대역을 공유한다. 재고를 바꾸지 않는 조회 전용이다)
// 실행: k6 run l5-cache-stampede.js   (앱은 pms.search.cache.enabled=true 로 기동)

import http from 'k6/http';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import { BASE_URL, PATHS, PLAN, SEARCH_FIELDS, nightsAfter } from './config.js';
import { installResponseCallback } from './lib/api.js';

const RANGE = PLAN.s8.dateRange;
const RATE = Number(__ENV.RATE || 300);
const DURATION = __ENV.DURATION || '60s';

// source=DB 응답이 시간축 어디에 찍히는가. 10초 주기로 뭉치면 그게 스탬피드다.
const dbHitAt = new Trend('db_hit_elapsed_ms');
const dbHits = new Counter('db_hits');
const cacheHits = new Counter('cache_hits');

let startedAt = 0;

export const options = {
    scenarios: {
        stampede: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: DURATION,
            preAllocatedVUs: 200,
            maxVUs: 400,
        },
    },
    // 합격선을 두지 않는다. 관찰이 목적이다.
    // 다만 앱이 죽으면 관찰 자체가 무의미하므로 5xx만 막는다.
    thresholds: {
        http_req_failed: ['rate<0.01'],
    },
};

// 캐시 키는 avail:{hotelId}:{checkIn}:{checkOut}:{guestCount}:{roomCount} 다.
// 아래 조건을 고정하면 모든 요청이 같은 키를 노린다.
const FIXED = {
    hotelId: 1,
    checkIn: RANGE[0],
    checkOut: nightsAfter(RANGE[0], 2),
    guestCount: 2,
    roomCount: 1,
};

export function setup() {
    installResponseCallback();
    console.log(`[L5] 캐시 키 하나에 ${RATE}/s x ${DURATION}. TTL 10초이므로 만료가 약 6회 발생한다.`);
    console.log(`[L5] 고정 조건: ${JSON.stringify(FIXED)}`);
    return { startedAt: Date.now() };
}

export default function (data) {
    const q = Object.entries(FIXED).map(([k, v]) => `${k}=${v}`).join('&');
    const res = http.get(`${BASE_URL}${PATHS.availability}?${q}`, { tags: { op: 'search' } });

    let body = null;
    try { body = res.json(); } catch (e) { /* ignore */ }

    const source = body && body[SEARCH_FIELDS.source];
    if (source === 'DB') {
        dbHits.add(1);
        // 시작 후 몇 ms에 DB로 갔는가. 이 분포가 뭉치는지가 핵심 관찰이다.
        dbHitAt.add(Date.now() - data.startedAt);
    } else if (source === 'CACHE') {
        cacheHits.add(1);
    }

    check(res, { 'L5: 200': (r) => r.status === 200 });
}

export function teardown() {
    console.log('[L5] 관찰 결과 읽는 법:');
    console.log('[L5]  1. db_hits / (db_hits + cache_hits) 가 캐시 미스율이다.');
    console.log('[L5]     TTL 10초 × 60초 = 만료 6회. 방어가 있다면 db_hits 가 6 근처여야 한다.');
    console.log('[L5]     수백이면 만료 순간마다 그만큼이 한꺼번에 DB로 간 것이다.');
    console.log('[L5]  2. db_hit_elapsed_ms 분포가 10초 간격으로 뭉치는지 본다. 뭉치면 스탬피드다.');
    console.log('[L5]  3. 같은 구간의 p99 응답 시간이 주기적으로 튀는지 함께 본다.');
    console.log('[L5]  4. HikariCP 활성 커넥션(최대 20)을 actuator/metrics 로 같이 기록한다.');
    console.log('[L5] 판단 기준: 만료 순간 DB 조회가 한 자릿수면 방어 불필요, 수십~수백이면 근거.');
    console.log('[L5] 결론은 F03이 내린다. F04는 숫자만 싣는다.');
}
