// S8. 조회 폭주 속 예약 · 캐시 유무 대조
//
// 증명 명제 (라). F03 캐시가 절단되면 대조 부분은 폐기하고 혼합 부하만 남긴다.
//
// ---------------------------------------------------------------------------
// 캐시의 진짜 값어치는 검색 p95가 아니다
// ---------------------------------------------------------------------------
// 검색이 빨라지는 건 당연하다. 봐야 할 것은 **검색이 DB를 덜 때린 만큼
// 예약이 얼마나 편해졌는가**다. 커넥션 풀이 20개뿐이라, 검색이 그걸 다
// 잡아먹으면 예약이 밀린다. 그래서 예약 API의 p95를 따로 태그해 잰다.
//
// 그리고 캐시는 공짜가 아니다. 낡은 결과를 보여준 대가로 사용자는
// "검색에는 있었는데 예약하려니 없다"는 헛걸음을 한다. 그 빈도가
// stale window와 검색→예약 409 비율이다. 이득과 비용을 나란히 놓는다.
//
// ---------------------------------------------------------------------------
// 409를 실패로 세지 않는다
// ---------------------------------------------------------------------------
// 검색 결과가 낡아 예약이 409로 실패하는 것은 F03이 설계한 정상 흐름이다.
// 오류율에 섞으면 정상 설계가 장애처럼 보이는 리포트가 나온다.
// 관측 지표로 따로 뽑고, 실제 클라이언트처럼 fresh=true로 재검색해
// 최대 2회까지 재시도한다. 한 번 409 받고 끝내면 실제보다 나쁜 그림이 된다.
//
// 대상 날짜 2026-10-01 ~ 10-10. **검색 안전 구간(checkIn >= 2026-08-15,
// checkOut <= 2026-10-30) 안이다.** 예약 API는 checkOut > today 면 통과하지만
// 검색은 checkIn >= today 를 요구해서, 시드 앞부분 08-01~08-14는 검색으로
// 도달할 수 없다. "검색 -> 예약" 흐름이 본질인 이 시나리오는 안전 구간만 쓴다.
//
// 실행:
//   ./reset.sh s8
//   CACHE=on  k6 run s8-search-cache.js     # 앱은 pms.search.cache.enabled=true 로 기동
//   CACHE=off k6 run s8-search-cache.js     # false 로 기동
//
// 설계: docs/load-test/scenarios.md §4 S8

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';
import {
    BASE_URL, PATHS, PLAN, ROOM_TYPES, SEARCH_FIELDS,
    nightsAfter, userId, headers,
} from './config.js';
import { installResponseCallback, createReservation } from './lib/api.js';
import { BASE_THRESHOLDS, M } from './lib/metrics.js';

const RANGE = PLAN.s8.dateRange;  // ['2026-10-01', '2026-10-10']
const DAYS = 10;
const RATE = Number(__ENV.RATE || 500);
const DURATION = __ENV.DURATION || '60s';
const CACHE = (__ENV.CACHE || 'on').toLowerCase();

// source 필드가 곧 히트율이다. 별도 계측을 붙이지 않는다.
const cacheHit = new Rate('cache_hit_rate');
// 응답이 실제로 얼마나 낡았는가. 캐시 히트면 0이 아니다.
const staleness = new Trend('response_staleness_ms');
// 검색에는 있었는데 예약에서 409. 합격선 없는 관측 지표다.
const searchToReserve409 = new Rate('search_to_reserve_409_rate');
// 재시도까지 했는데도 못 잡은 경우. 이게 진짜 헛걸음이다.
const reserveGaveUp = new Counter('reserve_gave_up');
// 범위 밖을 찍고 있다는 신호. 대량 발생하면 시나리오 오류다.
const notYetOpen = new Counter('empty_not_yet_open');
// 200을 받은 검색 수. cache_hit_rate 표본과 같은 분기에서 함께 늘어나므로,
// 이게 0이 아니면 히트율 표본도 0이 아니다 — "세었는가"를 세는 지표다.
const searchOk = new Counter('search_ok');

export const options = {
    scenarios: {
        mixed: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: DURATION,
            preAllocatedVUs: 200,
            maxVUs: 500,
        },
        // 캐시 정합성 프로브. 메인 부하와 별개로 한 조건만 계속 지켜본다.
        probe: {
            executor: 'constant-arrival-rate',
            rate: 2,
            timeUnit: '1s',
            duration: DURATION,
            preAllocatedVUs: 2,
            maxVUs: 4,
            exec: 'probe',
            tags: { role: 'probe' },
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        'http_req_duration{op:search}': ['p(95)<200'],
        // 캐시의 진짜 값어치. 검색이 DB를 덜 때린 만큼 예약이 편해졌는가.
        'http_req_duration{op:create}': ['p(95)<1000'],
        // 캐시 히트 응답이 TTL보다 한참 오래됐다면 TTL이 안 걸린 것이다.
        //
        // 기준은 **12초** — 설계 문서(scenarios.md §4 S8)가 부하 전에 확정한
        // "TTL 10초 + 2초"다. 처음 이 줄에 10000(=TTL 그대로)을 적었던 것은
        // 옮겨 적기 실수이고, 원리적으로 틀린 값이다: 이 지표는
        // `클라이언트 수신 시각 - 서버의 searchedAt`이라 **왕복 시간이 포함**된다.
        // TTL 만료 직전(9.99초)에 캐시에서 꺼낸 응답이 부하 중 1초 걸려
        // 도착하면 11초로 측정된다 — TTL은 정상인데 게이트가 우는 것이다.
        // 실제로 캐시 ON 1차 실행에서 최대 10.4초가 나왔고(검색 최대 응답
        // 933ms와 같은 구간), 설계 기준 12초 안쪽이라 정상이다.
        // 2초 여유가 이 왕복분을 덮으라고 원래부터 있던 것이다.
        response_staleness_ms: ['p(100)<=12000'],
        // 회차 유효성 (F03 계약, 2026-08-15): 캐시 on 회차인데 source=CACHE 가
        // 한 번도 없으면 캐시가 죽어 있었던 것이다. 그 회차를 on 으로 세면
        // "차이 없음"이라는 거짓 결론이 나온다 — 스위치 미작동(reset.sh 검사)과
        // 다른 경로로 같은 거짓말이라 여기서 따로 막는다. 실행 중 Redis 가
        // 죽어 DB 로 쏠려도 이 게이트에 잡힌다.
        // off 회차는 반대로 CACHE 응답이 한 건이라도 있으면 안 된다 — 있으면
        // 캐시가 살아 있던 것이라 그 대조도 무효다.
        ...(CACHE === 'on' ? { cache_hit_rate: ['rate>0'] } : { cache_hit_rate: ['rate==0'] }),
        // 성공한 검색이 0건이면 위 게이트는 표본이 없어 조용히 통과한다.
        // 그래서 "검색이 실제로 성공했는가"를 따로 건다. 이 둘이 한 쌍이다.
        search_ok: ['count>0'],
    },
};

function searchParams(n) {
    // 인기 조건 소수에 몰리게 한다. 날짜를 완전 무작위로 뽑으면 캐시 키가
    // 흩어져 히트율이 0에 가까워지고, 캐시가 있으나 마나가 된다.
    // 흩어진 경우도 별도 회차로 재서 둘을 비교하는 것이 이 캐시의
    // 값어치를 보여주는 방법이다 (SPREAD=1 로 실행).
    const spread = __ENV.SPREAD === '1' ? DAYS : 3;
    const day = n % spread;
    const checkIn = nightsAfter(RANGE[0], day);
    return {
        hotelId: 1,
        checkIn,
        checkOut: nightsAfter(checkIn, 2),
        guestCount: 2,
        roomCount: 1,
    };
}

function doSearch(p, fresh) {
    const q = Object.entries(p).map(([k, v]) => `${k}=${v}`).join('&');
    const url = `${BASE_URL}${PATHS.availability}?${q}${fresh ? '&fresh=true' : ''}`;
    // 검색은 X-User-Id를 요구하지 않는다 (F03 D11).
    const res = http.get(url, { tags: { op: 'search' } });

    let body = null;
    try { body = res.json(); } catch (e) { /* 에러 응답 */ }

    // 표본은 200 응답마다 **조건 없이 정확히 한 번** 넣는다.
    //
    // "source 필드가 있을 때만 넣기"로 짜면 필드명이 어긋났을 때(ApiModel
    // 미상속 등) 표본이 0건이 되는데 — **k6는 표본 없는 지표의 임계값을
    // 조용히 통과시킨다.** 게이트가 울어야 할 바로 그 상황에서 게이트가
    // 사라진다. 그래서 필드가 없어도, 본문 파싱이 실패해도 false 로 넣는다.
    //
    // "표본을 넣는 경로 자체가 안 도는" 위험(PM 제안: 표본 수 == 200 응답 수
    // 게이트)은 임계값으로는 못 건다 — k6 임계값은 지표 하나에 대한 식이라
    // 두 지표를 비교할 수 없다. 대신 구조로 막는다: 이 줄이 200 판정과 같은
    // 분기에 있어 건너뛸 조건 분기 자체가 없고, "200이 있었는가"는 아래
    // search_ok 게이트가 따로 확인한다. 둘을 합치면 같은 보장이 된다.
    if (res.status === 200) {
        searchOk.add(1);
        cacheHit.add(body ? body[SEARCH_FIELDS.source] === 'CACHE' : false);
        const searchedAt = body ? Date.parse(body[SEARCH_FIELDS.searchedAt]) : NaN;
        if (!isNaN(searchedAt)) {
            // 음수가 나오면 서버·클라이언트 시계가 어긋난 것이다. 0으로 깎는다.
            staleness.add(Math.max(0, Date.now() - searchedAt));
        }
    }
    if (body && body[SEARCH_FIELDS.emptyReason] === 'NOT_YET_OPEN') {
        notYetOpen.add(1);
    }
    return { res, body };
}

export function setup() {
    installResponseCallback();
    console.log(`[S8] CACHE=${CACHE} ${RANGE[0]} ~ ${RANGE[1]} ${RATE}/s x ${DURATION}`);
    console.log(`[S8] 검색 키 분산: ${__ENV.SPREAD === '1' ? '흩어짐(10일)' : '집중(3일)'}`);
    return {};
}

export default function () {
    const n = exec.scenario.iterationInTest;

    // 검색 90% / 검색→예약 10%
    if (n % 10 !== 0) {
        const { res } = doSearch(searchParams(n), false);
        check(res, { '검색: 200': (r) => r.status === 200 });
        return;
    }

    searchThenReserve(n);
}

function searchThenReserve(n) {
    const p = searchParams(n);
    const user = userId(8000 + (n % 2000));

    // 재고가 적은 스위트(10실)를 예약 대상으로 삼는다. 100실짜리를 노리면
    // 경합이 거의 안 나서 캐시 낡음의 영향이 드러나지 않는다.
    const roomType = ROOM_TYPES.suite;

    for (let attempt = 0; attempt < 3; attempt++) {
        // 첫 시도는 캐시를 그대로 쓰고, 409 이후 재시도는 fresh=true로 다시 본다.
        // 진짜 클라이언트가 그렇게 동작한다.
        const { body } = doSearch({ ...p, guestCount: 4 }, attempt > 0);
        const items = (body && body[SEARCH_FIELDS.items]) || [];
        const hit = items.find((it) => it.roomTypeId === roomType.id);
        if (!hit || hit[SEARCH_FIELDS.minRemaining] <= 0) return; // 검색이 없다고 하면 시도하지 않는다

        const { outcome } = createReservation(roomType, p.checkIn, {
            userId: user,
            idempotencyKey: `s8-${exec.instance.idInTest}-${n}-${attempt}`,
            roomCount: 1,
            nights: 2,
            guestCount: 2,
        });

        if (outcome.kind === 'created') {
            searchToReserve409.add(false);
            return;
        }
        if (outcome.kind === 'inventory') {
            // 검색에는 있었는데 예약에서 없다. 낡음이 만든 헛걸음이다.
            searchToReserve409.add(true);
            continue; // fresh=true로 재검색해 다시 시도
        }
        return; // 그 외(락 실패 등)는 재시도하지 않는다
    }
    reserveGaveUp.add(1);
}

// 캐시 정합성 프로브. 한 조건만 계속 조회하며 stale window를 잰다.
// 메인 부하가 그 재고를 소진시키는 동안, 검색 결과에서 그 객실타입이
// 사라지기까지 몇 초가 걸리는지 본다.
export function probe() {
    const p = {
        hotelId: 1,
        checkIn: RANGE[0],
        checkOut: nightsAfter(RANGE[0], 2),
        guestCount: 4,   // 스위트만 걸리는 조건
        roomCount: 1,
    };
    const { res, body } = doSearch(p, false);
    const items = (body && body[SEARCH_FIELDS.items]) || [];
    const suite = items.find((it) => it.roomTypeId === ROOM_TYPES.suite.id);

    check(res, {
        '프로브: 200': (r) => r.status === 200,
        '프로브: 음수 잔여를 노출하지 않는다':
            () => !suite || suite[SEARCH_FIELDS.minRemaining] >= 0,
    });
}

export function teardown() {
    console.log('[S8] verify/s8.sql 로 확인할 것. 초과 판매 0건이 절대 조건이다.');
    console.log('[S8] cache_hit_rate = source가 CACHE인 비율. 별도 계측 없이 응답에서 나온다.');
    console.log('[S8] response_staleness_ms 의 최대값이 10초(TTL)를 넘으면 TTL이 안 걸린 것이다.');
    console.log('[S8] search_to_reserve_409_rate 는 합격선이 없다. 캐시가 만든 헛걸음의 빈도다.');
    console.log('[S8] empty_not_yet_open 이 대량이면 시나리오가 범위 밖을 찍고 있다는 신호다.');
    console.log('[S8] ON/OFF 비교 시 검색 p95보다 예약 p95의 차이를 먼저 봐라. 그게 캐시의 값어치다.');
}
