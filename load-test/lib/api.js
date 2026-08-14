// F04 부하테스트 — API 호출 래퍼
//
// 시나리오 스크립트는 URL을 직접 만들지 않는다. 전부 이 파일을 거친다.
// F01의 D7(confirmationCode)이 기각돼 경로가 /{code} -> /{id}로 바뀌어도
// config.js의 pathFor()와 idField()만 고치면 여기서 흡수된다.

import http from 'k6/http';
import { BASE_URL, PATHS, ACTIONS, pathFor, headers, reservationBody } from '../config.js';
import { classifyCreate, classifyTransition } from './metrics.js';

// 409는 실패가 아니다. http_req_failed가 409를 실패로 세지 않게 한다 (§3-1).
// 400·404·503·5xx는 커스텀 카운터로 따로 세므로 기대 상태에 넣지 않는다.
export function installResponseCallback() {
    http.setResponseCallback(http.expectedStatuses(200, 201, 409));
}

// roomType은 config.ROOM_TYPES의 객체를 그대로 넘긴다.
// id만 넘기지 않는 이유: capacity가 있어야 guestCount를 정원 안쪽으로 계산한다.
export function createReservation(roomType, checkInDate, opts = {}) {
    const res = http.post(
        `${BASE_URL}${PATHS.create}`,
        JSON.stringify(reservationBody(roomType, checkInDate, opts)),
        { headers: headers(opts.userId, opts.idempotencyKey), tags: { op: 'create' } },
    );
    return { res, outcome: classifyCreate(res) };
}

function transition(ref, action, opts = {}) {
    const res = http.post(
        `${BASE_URL}${pathFor(ref, action)}`,
        null,
        { headers: headers(opts.userId), tags: { op: action } },
    );
    return { res, outcome: classifyTransition(res, { action, priorStatus: opts.priorStatus }) };
}

export const confirm = (ref, opts) => transition(ref, ACTIONS.confirm, opts);
export const cancel = (ref, opts) => transition(ref, ACTIONS.cancel, opts);
export const checkIn = (ref, opts) => transition(ref, ACTIONS.checkIn, opts);
export const checkOut = (ref, opts) => transition(ref, ACTIONS.checkOut, opts);

export function get(ref, opts = {}) {
    return http.get(`${BASE_URL}${pathFor(ref)}`, {
        headers: headers(opts.userId),
        tags: { op: 'get' },
    });
}

// 만료 배치 트리거. S4-B가 반복 호출한다.
// 응답의 expiredCount 합계를 최종 EXPIRED 건수와 대조해 이중 만료를 잡는다.
export function triggerExpire(opts = {}) {
    return http.post(`${BASE_URL}${PATHS.expire}`, null, {
        headers: headers(opts.userId || 'user-batch'),
        tags: { op: 'expire' },
    });
}

// NO_SHOW 트리거.
// F01 D4가 절단 1순위라 이 함수를 쓰는 시나리오는 보조 실험으로만 둔다.
export function triggerNoShow(opts = {}) {
    return http.post(`${BASE_URL}${PATHS.noShow}`, null, {
        headers: headers(opts.userId || 'user-batch'),
        tags: { op: 'no-show' },
    });
}
