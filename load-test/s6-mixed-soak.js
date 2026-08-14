// S6. 혼합 지속 부하 — 재고 누수 검출
//
// 증명 명제 (가)(다) 종합.
//
// ---------------------------------------------------------------------------
// 앞의 시나리오들이 못 잡는 것
// ---------------------------------------------------------------------------
// S1~S4는 짧고 단일 동작이다. 실제 사고는 예약·확정·취소가 오래 섞여 돌 때
// 재고가 슬금슬금 어긋나는 형태로 온다. 취소는 성공했는데 복원이 안 되거나,
// 만료가 복원을 두 번 하거나 하는 것들이다.
//
// 그리고 보존식(잔여 + 점유 = 총량)만으로는 **두 번 깎고 두 번 되돌린 경우**를
// 놓친다. 최종 잔여만 보면 맞아떨어져서 통과한다. 그런데 실제로는 이중 차감과
// 이중 복원이 일어났고, 타이밍이 조금만 달랐으면 음수로 내려갔거나 총량을
// 넘었을 것이다. 지금 통과한 건 운이다.
//
// 그래서 두 각도로 본다.
//   1. 보존식     — 최종 상태가 맞는가
//   2. 이력 줄 수 — 예약당 재고 복원 이벤트가 정확히 한 줄인가
// 2번이 이 시나리오의 고유 가치다. 이력 테이블은 성공한 전이만 기록하므로,
// 복원 이벤트(CANCEL·PAYMENT_FAILED·EXPIRE)가 두 줄이면 이중 복원이다.
//
// 설계: docs/load-test/scenarios.md §4 S6
// 실행 전: ./reset.sh s6

import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import {
    BASE_URL, PATHS, ALL_ROOM_TYPES, ROOM_TYPES, PLAN, STATUS,
    idField, nightsAfter, headers, reservationBody,
} from './config.js';
import { installResponseCallback, createReservation, confirm, cancel, get } from './lib/api.js';
import { BASE_THRESHOLDS } from './lib/metrics.js';

const RANGE = PLAN.s6.dateRange; // ['2026-09-21', '2026-09-30']
const DAYS = 10;
const RATE = Number(__ENV.RATE || 200);
const DURATION = __ENV.DURATION || '5m';

// 이 시나리오가 만든 예약 중 확정·취소 대상으로 쓸 수 있는 것들.
// VU마다 메모리가 분리되므로 각 VU가 자기가 만든 것만 들고 간다.
// 그래야 소유자(userId)가 자동으로 맞아 404를 피한다.
const mine = [];

const createdTotal = new Counter('soak_created');
const cancelledTotal = new Counter('soak_cancelled');
const confirmedTotal = new Counter('soak_confirmed');

// 과거 체크아웃 프로브.
//
// F01의 규칙은 대부분 DB CHECK 제약이 최후 방어선으로 받쳐준다. 애플리케이션이
// 뚫려도 DB에서 멈춘다. 그런데 `checkOut > today` 하나만 예외다 —
// MySQL CHECK에 CURDATE()를 쓸 수 없어 원리적으로 제약을 걸 수 없고,
// **애플리케이션 검증 한 겹이 전부다.**
//
// 방어선이 한 겹뿐인 곳은 뚫려보는 값이 있다. 소량만 섞는다.
const probeRejected = new Counter('past_checkout_rejected');  // 400으로 막힘 = 정상
const probeLeaked = new Counter('past_checkout_leaked');      // 통과 = 규칙이 뚫렸다

export const options = {
    scenarios: {
        soak: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: DURATION,
            preAllocatedVUs: 150,
            maxVUs: 300,
        },
    },
    thresholds: {
        ...BASE_THRESHOLDS,
        http_req_duration: ['p(95)<1000'],
        // 방어선이 한 겹뿐인 규칙이 실제로 막는가. 하드 게이트다.
        past_checkout_leaked: ['count==0'],
    },
};

function dateAt(i) {
    return nightsAfter(RANGE[0], i % DAYS);
}

export function setup() {
    installResponseCallback();
    console.log(`[S6] ${RANGE[0]} ~ ${RANGE[1]} (${DAYS}일) × 전 객실타입, ${RATE}/s × ${DURATION}`);
    return {};
}

export default function () {
    const n = exec.scenario.iterationInTest;
    // 이 VU를 고정 사용자에 묶는다. 자기가 만든 예약만 건드리므로 404가 안 난다.
    const owner = `user-6${String(exec.vu.idInTest).padStart(4, '0')}`;
    const roll = n % 20;

    // 50회에 1번(2%)만 과거 체크아웃 프로브를 섞는다. 무거울 필요가 없다.
    if (n % 50 === 0) {
        pastCheckoutProbe(owner, n);
        return;
    }

    // 예약 60% / 확정 20% / 취소 15% / 조회 5%
    if (roll < 12) {
        doCreate(owner, n);
    } else if (roll < 16) {
        doTransition(owner, 'confirm');
    } else if (roll < 19) {
        doTransition(owner, 'cancel');
    } else {
        doGet(owner);
    }
}

// 이미 끝난 투숙을 예약하려 시도한다. 400으로 막혀야 한다.
//
// classifyCreate를 쓰지 않고 직접 호출하는 이유:
//   이 프로브의 400은 **의도된 것**이라 bad_request(하드 게이트, 0이어야 함)에
//   섞이면 안 된다. §3-6의 "400을 만들지 않는다" 규약은 경합을 재는 요청에
//   대한 것이고, 이건 규칙을 시험하는 요청이라 성격이 다르다.
function pastCheckoutProbe(owner, n) {
    // 시드 범위 안이면서 이미 지난 날짜. 오늘이 2026-08-15이므로 08-02~08-04는
    // checkOut이 과거다. 재고 행 자체는 존재하므로 "행이 없어서" 막히는 것과
    // 구분된다 — 순수하게 날짜 규칙만 시험한다.
    const body = reservationBody(ROOM_TYPES.standard, '2026-08-02', { nights: 2 });
    const res = http.post(`${BASE_URL}${PATHS.create}`, JSON.stringify(body), {
        headers: headers(owner, `s6-probe-${exec.vu.idInTest}-${n}`),
        tags: { op: 'past_checkout_probe' },
    });

    if (res.status === 400) {
        probeRejected.add(1);
    } else if (res.status === 201 || res.status === 200) {
        // 규칙이 뚫렸다. DB CHECK가 없으므로 이 행은 그대로 저장된다.
        probeLeaked.add(1);
    }

    check(res, {
        '과거 체크아웃은 400으로 막힌다': (r) => r.status === 400,
    });
}

function doCreate(owner, n) {
    // 날짜와 객실타입을 흩어 여러 재고 행에 부하를 분산한다.
    const roomType = ALL_ROOM_TYPES[n % ALL_ROOM_TYPES.length];
    const { res, outcome } = createReservation(roomType, dateAt(n), {
        userId: owner,
        idempotencyKey: `s6-${exec.vu.idInTest}-${n}`,
        roomCount: 1,
    });

    if (outcome.kind === 'created') {
        createdTotal.add(1);
        // 뒤에서 확정·취소 대상으로 쓴다. 무한히 쌓이지 않게 상한을 둔다.
        if (mine.length < 200) {
            mine.push({ ref: outcome.body[idField()], status: STATUS.PENDING });
        }
    }

    check(res, {
        '생성: 5xx 아님': () => outcome.kind !== 'error',
        '생성: 400 아님': () => outcome.kind !== 'bad_request',
    });
}

function doTransition(owner, action) {
    const target = mine.shift();
    if (!target) return;

    const call = action === 'confirm' ? confirm : cancel;
    const { res, outcome } = call(target.ref, {
        userId: owner,
        priorStatus: target.status,
    });

    if (outcome.kind === 'ok') {
        if (outcome.status === STATUS.CONFIRMED) {
            confirmedTotal.add(1);
            // 확정된 것은 나중에 취소 대상으로 다시 넣는다.
            // CONFIRMED -> CANCEL 도 전이 표 안이라 정상 경로다.
            if (mine.length < 200) mine.push({ ref: target.ref, status: STATUS.CONFIRMED });
        } else if (outcome.status === STATUS.CANCELLED) {
            cancelledTotal.add(1);
        }
    }

    check(res, {
        [`${action}: 5xx 아님`]: () => outcome.kind !== 'error',
        [`${action}: 404 아님`]: () => outcome.kind !== 'not_found',
    });
}

function doGet(owner) {
    if (mine.length === 0) return;
    const target = mine[mine.length - 1];
    const res = get(target.ref, { userId: owner });
    check(res, { '조회: 5xx 아님': (r) => r.status < 500 });
}

export function teardown() {
    console.log('[S6] verify/s6.sql 로 확인할 것. 이 시나리오는 검증이 본론이다.');
    console.log('[S6] 1. 보존식: 모든 (객실타입, 날짜)에서 잔여 + 점유 = total_quantity. 어긋난 행 0건');
    console.log('[S6] 2. remaining < 0 인 행 0건 (초과 판매)');
    console.log('[S6] 3. remaining > total_quantity 인 행 0건 (복원 과다 — 없는 방을 파는 것)');
    console.log('[S6] 4. 이력: 예약당 재고 복원 이벤트가 정확히 1줄. 2줄이면 이중 복원이다.');
    console.log('[S6] 4번이 이 시나리오의 고유 가치다. 보존식만으로는 두 번 깎고 두 번 되돌린 경우를 놓친다.');
}
