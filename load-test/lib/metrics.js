// F04 부하테스트 — 공통 지표와 응답 분류
//
// 모든 시나리오가 같은 이름으로 센다. 그래야 리포트에서 시나리오 간 비교가 된다.
// 근거: docs/load-test/scenarios.md §3-1, §3-2
//
// 이 파일이 존재하는 이유:
//   부하테스트에서 가장 쉽게 틀리는 지점이 "거절을 실패로 세는 것"이다.
//   409(재고 소진·중복·금지 전이)는 시스템이 옳게 동작한 증거이고,
//   결제 거절은 HTTP 200을 주면서 본문 status가 CANCELLED가 된다.
//   분류 로직이 시나리오마다 흩어지면 한 곳만 틀려도 리포트가 어긋나므로
//   여기 한 곳에 모은다.

import { Counter } from 'k6/metrics';
import { ERROR_CODE, RESPONSE_FIELDS, STATUS, IDEMPOTENT_CELLS, ACTION_EVENT, isExplainable200 } from '../config.js';

export const M = {
    rsvCreated: new Counter('rsv_created'),
    rsvReplayed: new Counter('rsv_replayed'),
    transitionOk: new Counter('transition_ok'),
    transitionIdem: new Counter('transition_idem'),
    paymentDeclined: new Counter('payment_declined'),
    rejInventory: new Counter('rej_inventory'),
    rejDuplicate: new Counter('rej_duplicate'),
    rejTransition: new Counter('rej_transition'),
    badRequest: new Counter('bad_request'),
    lockFailed: new Counter('lock_failed'),
    serverError: new Counter('server_error'),
    // 404는 앱 버그가 아니라 거의 항상 시나리오 버그다.
    // 취소·확정이 소유자를 검증하는데 남의 예약이면 403이 아니라 404를 준다
    // (확인번호의 존재 자체를 숨기는 설계). 요청마다 X-User-Id가 바뀌면
    // 전이 요청이 전부 404로 떨어지는데, 404는 "예약이 없다"로 읽혀서
    // 원인을 찾는 데 오래 걸린다. 그래서 따로 세고 하드 게이트로 둔다.
    notFound: new Counter('not_found'),
    // 거부 34칸에서 200이 나왔다. 명제 (다)의 직접적인 반증이다.
    // 성능 지표가 아니라 결론을 뒤집는 사건이므로 하드 게이트로 둔다.
    forbiddenPassed: new Counter('forbidden_transition_passed'),
};

function parse(res) {
    try {
        return res.json();
    } catch (e) {
        return null;
    }
}

// 생성 요청(POST /api/reservations)의 응답을 분류한다.
//
// 반환: { kind, body }
//   kind = 'created' | 'replayed' | 'inventory' | 'duplicate'
//        | 'bad_request' | 'lock_failed' | 'error'
export function classifyCreate(res) {
    const body = parse(res);
    const code = body && body.code;

    if (res.status === 201) {
        M.rsvCreated.add(1);
        return { kind: 'created', body };
    }
    // 최초 201 / 재요청 200. 상태 코드만으로 갈린다 (F01 계약 D18).
    if (res.status === 200) {
        M.rsvReplayed.add(1);
        return { kind: 'replayed', body };
    }
    if (res.status === 409) {
        if (code === ERROR_CODE.INSUFFICIENT_INVENTORY) {
            M.rejInventory.add(1);
            return { kind: 'inventory', body };
        }
        if (code === ERROR_CODE.DUPLICATE_REQUEST || code === ERROR_CODE.REQUEST_IN_PROGRESS) {
            M.rejDuplicate.add(1);
            return { kind: 'duplicate', body };
        }
        // 생성 요청에 전이 오류가 오면 그것대로 이상하지만, 삼키지 않고 센다.
        M.rejTransition.add(1);
        return { kind: 'transition', body };
    }
    if (res.status === 400) {
        // 앱 버그가 아니라 내 시나리오가 잘못된 요청을 보낸 것이다 (§3-6).
        M.badRequest.add(1);
        return { kind: 'bad_request', body };
    }
    if (res.status === 503 && code === ERROR_CODE.LOCK_ACQUISITION_FAILED) {
        M.lockFailed.add(1);
        return { kind: 'lock_failed', body };
    }
    M.serverError.add(1);
    return { kind: 'error', body };
}

// 전이 요청(confirm/cancel/check-in/check-out)의 응답을 분류한다.
//
// expectedStatus를 주면 "상태가 실제로 바뀌었는가"와 "이미 그 상태였는가"를
// 구분해 센다. 확정 요청은 결제 거절(200 + CANCELLED)이 섞이므로
// 반드시 본문 status까지 읽는다.
//
// 반환: { kind, status, body }
//   kind = 'ok' | 'idempotent' | 'declined' | 'transition'
//        | 'bad_request' | 'lock_failed' | 'error'
export function classifyTransition(res, opts = {}) {
    const body = parse(res);
    const code = body && body.code;
    const status = body && body[RESPONSE_FIELDS.status];

    if (res.status === 200) {
        // 전이 표 49칸 = 허용 8 + 멱등 7 + 거부 34.
        // 200이 나왔다면 앞의 15칸 중 하나로 설명돼야 한다.
        // 거부 34칸에서 200이 나왔다면 금지 전이가 통과한 것이다.
        // 이건 성능 지표가 아니라 명제 (다)의 반증이므로 즉시 실패로 센다.
        if (!isExplainable200(opts.priorStatus, opts.action, status)) {
            M.forbiddenPassed.add(1);
            return { kind: 'forbidden_passed', status, body };
        }
        // 결제 거절. 실패가 아니라 정상 처리 결과다 (§3-1).
        //
        // **200 + CANCELLED가 나오는 경로는 결제 거절 하나뿐이다.**
        // 확정이 경합에서 지면 조건부 UPDATE가 0건을 반환해 409가 나가고,
        // 이미 취소된 예약에 확정을 걸어도 전이 표상 거부라 409다.
        // 그래서 상태 코드만으로 "졌다"와 "거절됐다"가 갈린다 — 최종 상태를
        // 역추적할 필요가 없다.
        if (opts.action === 'confirm' && status === STATUS.CANCELLED) {
            M.paymentDeclined.add(1);
            return { kind: 'declined', status, body };
        }
        // 이미 그 상태였다면 멱등 전이다 (멱등 성공 7칸).
        if (opts.priorStatus && status === opts.priorStatus) {
            M.transitionIdem.add(1);
            return { kind: 'idempotent', status, body };
        }
        M.transitionOk.add(1);
        return { kind: 'ok', status, body };
    }
    if (res.status === 409) {
        if (code === ERROR_CODE.INVALID_STATE_TRANSITION) {
            M.rejTransition.add(1);
            return { kind: 'transition', status, body };
        }
        M.rejDuplicate.add(1);
        return { kind: 'duplicate', status, body };
    }
    if (res.status === 400) {
        M.badRequest.add(1);
        return { kind: 'bad_request', status, body };
    }
    // 소유자 불일치. 예약을 만든 VU가 끝까지 들고 가지 않았다는 뜻이다.
    if (res.status === 404) {
        M.notFound.add(1);
        return { kind: 'not_found', status, body };
    }
    if (res.status === 503 && code === ERROR_CODE.LOCK_ACQUISITION_FAILED) {
        M.lockFailed.add(1);
        return { kind: 'lock_failed', status, body };
    }
    M.serverError.add(1);
    return { kind: 'error', status, body };
}

// 모든 시나리오가 공유하는 임계값.
// 시나리오별 임계값은 여기에 얹어 쓴다.
//
// 셋 다 하드 게이트다. 0이 아니면 성능 미달이 아니라 **무효 실행**이므로
// 결과를 폐기하고 원인을 고쳐 다시 돌린다 (§3-6).
//   server_error : 앱 장애
//   bad_request  : 내 요청이 틀렸다
//   not_found    : 예약 소유자를 잘못 물려 보냈다
export const BASE_THRESHOLDS = {
    server_error: ['count==0'],
    bad_request: ['count==0'],
    not_found: ['count==0'],
    forbidden_transition_passed: ['count==0'],
};
