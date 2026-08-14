// F04 부하테스트 — 단일 진실 지점(single source of truth)
//
// API 계약이 바뀌면 이 파일만 고친다. 시나리오 스크립트는 여기서만 값을 가져간다.
//
// 왜 한 곳에 몰아넣는가:
//   F01의 D7(확인번호 기반 경로)이 기각되면 경로가 /{code} -> /{id} 정수로 바뀐다.
//   그때 시나리오 8개를 전부 고치는 대신 아래 pathFor()/idField()만 고치면 끝난다.
//
// 근거: docs/load-test/scenarios.md §6 (F01 계약·시드 확정본, 2026-08-15)

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

// ---------------------------------------------------------------------------
// 승인 리스크 스위치
// ---------------------------------------------------------------------------
//
// F01의 [필수] 결정 중 셋이 아직 관리자 승인 전이며, 기각되면 계약이 바뀐다.
// 스크립트를 고치는 대신 아래 플래그만 뒤집어 대응한다.
//
//   D7 confirmationCode -> 기각 시 CODE_BASED_PATH=false (경로·응답 필드가 id로)
//   D1 guestCount       -> 기각 시 SEND_GUEST_COUNT=false (본문에서 필드 제거)
//   D4 NO_SHOW          -> F01 스스로 "일정 밀리면 여기부터 자르자"고 추천했다.
//                          절단 가능성이 가장 높으므로 NO_SHOW를 쓰는 코드는
//                          이 플래그로 격리해, 꺼져도 나머지가 안 무너지게 한다.
export const FEATURES = {
    codeBasedPath: __ENV.CODE_BASED_PATH !== 'false',
    sendGuestCount: __ENV.SEND_GUEST_COUNT !== 'false',
    noShow: __ENV.NO_SHOW_ENABLED !== 'false',
};

// ---------------------------------------------------------------------------
// 엔드포인트 — 계약 확정본
// ---------------------------------------------------------------------------

export const PATHS = {
    create: '/api/reservations',
    expire: '/api/internal/reservations/expire',
    noShow: '/api/internal/reservations/no-show',
    health: '/actuator/health',
    // F03 검색. X-User-Id를 요구하지 않는다 (F03 스펙 D11).
    availability: '/api/availability',
};

// F02 특가. 경로에 객실타입과 투숙일이 들어간다.
// 특가 예약은 1실 고정이다 (F02 D4).
export function promotionPath(roomTypeId, stayDate, sub) {
    const base = `/api/promotions/${roomTypeId}/${stayDate}`;
    return sub ? `${base}/${sub}` : base;
}

// 예약 식별자를 경로로 바꾸는 유일한 함수.
// D7이 기각되면 여기와 idField()만 바꾼다. 다른 파일은 손대지 않는다.
export function pathFor(ref, action) {
    const base = `/api/reservations/${ref}`;
    return action ? `${base}/${action}` : base;
}

export function idField() {
    return FEATURES.codeBasedPath ? 'confirmationCode' : 'id';
}

export const ACTIONS = {
    confirm: 'confirm',
    cancel: 'cancel',
    checkIn: 'check-in',
    checkOut: 'check-out',
};

// ---------------------------------------------------------------------------
// 요청·응답 필드명 — 계약 확정본
// ---------------------------------------------------------------------------

export const FIELDS = {
    roomTypeId: 'roomTypeId',
    checkIn: 'checkIn',
    checkOut: 'checkOut',
    roomCount: 'roomCount',
    guestCount: 'guestCount',
};

export const RESPONSE_FIELDS = {
    status: 'status',
    totalPrice: 'totalPrice',
    expiresAt: 'expiresAt',
    expiredCount: 'expiredCount',
};

// ---------------------------------------------------------------------------
// 상태와 에러 코드 — 계약 확정본
// ---------------------------------------------------------------------------

export const STATUS = {
    PENDING: 'PENDING',
    CONFIRMED: 'CONFIRMED',
    CHECKED_IN: 'CHECKED_IN',
    CHECKED_OUT: 'CHECKED_OUT',
    CANCELLED: 'CANCELLED',
    EXPIRED: 'EXPIRED',
    NO_SHOW: 'NO_SHOW',
};

// 재고를 점유하지 않는 종료 상태. 보존식의 "활성 예약"에서 제외된다.
// NO_SHOW는 재고를 복원하지 않으므로 여기 넣지 않는다 (전이 표 참조).
export const RELEASED_STATUSES = [STATUS.CANCELLED, STATUS.EXPIRED];

// ---------------------------------------------------------------------------
// 전이 표 49칸 = 허용 전이 8 + 멱등 성공 7 + 거부 34
// ---------------------------------------------------------------------------
//
// 멱등 성공 7칸: 상태가 안 바뀌고 200이 나가는 조합이다.
//
// 판정 규칙이 이 표 덕에 단순해진다:
//   **200을 받았다면 허용 전이 8칸이거나 아래 7칸 중 하나여야 한다.**
//   나머지 34칸에서 200이 나오면 금지 전이가 통과한 것이므로 즉시 실패다.
//
// NO_SHOW 칸은 F01 D4에 걸려 있다. D4가 기각되면 이 칸이 사라지고
// 49칸이 36칸이 되므로, FEATURES.noShow 로 함께 껐다 켜지게 한다.
const IDEMPOTENT_CELLS_ALL = [
    [STATUS.CONFIRMED,   'CONFIRM'],
    [STATUS.CANCELLED,   'CANCEL'],
    [STATUS.CANCELLED,   'PAYMENT_FAILED'],
    [STATUS.EXPIRED,     'EXPIRE'],
    [STATUS.CHECKED_IN,  'CHECK_IN'],
    [STATUS.CHECKED_OUT, 'CHECK_OUT'],
    [STATUS.NO_SHOW,     'NO_SHOW'],
];

export const IDEMPOTENT_CELLS = IDEMPOTENT_CELLS_ALL
    .filter(([state]) => FEATURES.noShow || state !== STATUS.NO_SHOW)
    .map(([state, event]) => `${state}:${event}`);

// 허용 전이 8칸. (현재 상태, 이벤트) -> 다음 상태
const ALLOWED_ALL = {
    'PENDING:CONFIRM':          STATUS.CONFIRMED,
    'PENDING:PAYMENT_FAILED':   STATUS.CANCELLED,
    'PENDING:CANCEL':           STATUS.CANCELLED,
    'PENDING:EXPIRE':           STATUS.EXPIRED,
    'CONFIRMED:CANCEL':         STATUS.CANCELLED,
    'CONFIRMED:CHECK_IN':       STATUS.CHECKED_IN,
    'CONFIRMED:NO_SHOW':        STATUS.NO_SHOW,
    'CHECKED_IN:CHECK_OUT':     STATUS.CHECKED_OUT,
};

export const ALLOWED_TRANSITIONS = Object.fromEntries(
    Object.entries(ALLOWED_ALL).filter(([k]) => FEATURES.noShow || !k.endsWith(':NO_SHOW')),
);

// HTTP 액션 이름 -> 전이 표의 이벤트 이름
export const ACTION_EVENT = {
    'confirm': 'CONFIRM',
    'cancel': 'CANCEL',
    'check-in': 'CHECK_IN',
    'check-out': 'CHECK_OUT',
};

// 200 응답이 전이 표로 설명되는가.
// priorStatus를 모르면 판정할 수 없으므로 그때는 true로 둔다(별도 지표로 센다).
export function isExplainable200(priorStatus, action, resultStatus) {
    if (!priorStatus) return true;
    const event = ACTION_EVENT[action];
    if (!event) return true;
    const key = `${priorStatus}:${event}`;
    if (IDEMPOTENT_CELLS.includes(key)) return resultStatus === priorStatus;
    if (key in ALLOWED_TRANSITIONS) {
        // 결제 거절은 CONFIRM이 CANCELLED로 끝나는 정상 경로다.
        if (event === 'CONFIRM' && resultStatus === STATUS.CANCELLED) return true;
        return resultStatus === ALLOWED_TRANSITIONS[key];
    }
    return false; // 거부 34칸에서 200이 나왔다 -> 금지 전이 통과
}

export const ERROR_CODE = {
    INVALID_REQUEST: 'INVALID_REQUEST',
    RESOURCE_NOT_FOUND: 'RESOURCE_NOT_FOUND',
    INVALID_STATE_TRANSITION: 'INVALID_STATE_TRANSITION',
    INSUFFICIENT_INVENTORY: 'INSUFFICIENT_INVENTORY',
    DUPLICATE_REQUEST: 'DUPLICATE_REQUEST',
    REQUEST_IN_PROGRESS: 'REQUEST_IN_PROGRESS',
    LOCK_ACQUISITION_FAILED: 'LOCK_ACQUISITION_FAILED',
    // F02 특가
    PROMOTION_SOLD_OUT: 'PROMOTION_SOLD_OUT',
};

// F03 검색 응답 필드. 계측을 별도로 붙이지 않고 응답에서 직접 읽는다.
export const SEARCH_FIELDS = {
    source: 'source',                             // 'CACHE' | 'DB' — 이 비율이 곧 히트율이다
    searchedAt: 'searchedAt',                     // 응답 시각과의 차이 = 그 응답이 얼마나 낡았는가
    staleToleranceSeconds: 'staleToleranceSeconds',
    items: 'items',
    minRemaining: 'minRemaining',
    emptyReason: 'emptyReason',                   // SOLD_OUT | NOT_YET_OPEN | NO_FITTING_ROOM_TYPE
};

// 검색 파라미터의 안전 구간 (F03 계약 2절).
// 예약 API와 달리 검색은 과거 날짜를 400으로 막는다. 시드 범위 안이어도
// 오늘 이전은 검색으로 도달할 수 없다.
export const SEARCH_BOUNDS = {
    minCheckIn: '2026-08-15',   // 오늘. 이보다 앞이면 400
    maxCheckOut: '2026-10-30',  // 이보다 뒤면 200 + NOT_YET_OPEN
    maxNights: 30,
    hotelIds: [1, 2],           // 3 이상은 404
};

// ---------------------------------------------------------------------------
// 시드 — F01 확정본 (2026-08-15)
// ---------------------------------------------------------------------------
//
// 재고 날짜 범위는 CURDATE()가 아니라 고정 날짜다. 몇 번을 재시드해도
// 정확히 같은 상태가 나오므로, 어느 날 갑자기 스크립트가 깨지는 일이 없다.
export const SEED_RANGE = { start: '2026-08-01', end: '2026-10-29' };

// 초기 remaining은 전부 total_quantity와 같다. 줄여둔 날짜가 하나도 없다.
//
// 그래서 시나리오는 재고를 임의로 UPDATE하지 않고 "필요한 재고 수를 가진
// 객실타입"을 고른다. 이렇게 해야 reset.sh가 만드는 상태와 완전 재시드
// (docker compose down -v)가 만드는 상태가 정확히 같아진다.
// 재고를 손으로 바꾸면 보존식(remaining + 점유 = total_quantity)도 깨진다.
export const ROOM_TYPES = {
    standard:     { id: 1, hotelId: 1, capacity: 2, total: 100 },
    deluxe:       { id: 2, hotelId: 1, capacity: 3, total: 50 },
    suite:        { id: 3, hotelId: 1, capacity: 4, total: 10 },  // 경합 실험용
    oceanStandard:{ id: 4, hotelId: 2, capacity: 2, total: 80 },
    oceanSuite:   { id: 5, hotelId: 2, capacity: 4, total: 20 },
};

export const ALL_ROOM_TYPES = Object.values(ROOM_TYPES);

export function roomTypeById(id) {
    return ALL_ROOM_TYPES.find((rt) => rt.id === id);
}

// 시나리오별 대상 객실타입과 날짜 (scenarios.md §3-3).
//
// 날짜가 겹치면 시나리오끼리 간섭해 불변식 검증이 무의미해진다.
// 재고는 (객실타입, 날짜) 단위이므로, 한 타입으로 여러 건이 필요하면
// 날짜를 늘려 확보한다. 상태 전이 시나리오는 재고 경합이 목적이 아니라서
// 날짜를 흩어도 증명에 영향이 없다.
export const PLAN = {
    // 재고 10에 200요청. 스위트(10실)가 이 시나리오에 정확히 맞는다.
    s1:   { roomType: ROOM_TYPES.suite,      dates: ['2026-09-01'] },
    // 부분 소진. 20실에 1·2·3실 혼합 요청.
    s1c:  { roomType: ROOM_TYPES.oceanSuite, dates: ['2026-09-02'] },
    // 지속 부하 기준선. 100실.
    s2:   { roomType: ROOM_TYPES.standard,   dates: ['2026-09-03'] },
    // 멱등성. 재고 경합이 섞이면 안 되므로 넉넉한 타입을 쓴다.
    s3:   { roomType: ROOM_TYPES.standard,   dates: ['2026-09-04'] },
    // 취소×확정 300쌍. 100실 × 3일.
    s4:   { roomType: ROOM_TYPES.standard,   dates: ['2026-09-05', '2026-09-06', '2026-09-07'] },
    // 만료×확정 400건. 100실 × 4일.
    s4b:  { roomType: ROOM_TYPES.standard,   dates: ['2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11'] },
    // 락 대조. S2와 같은 부하를 날짜만 갈아 두 번 돌린다.
    // 09-14~16은 F02 특가가 점유했으므로 그 앞으로 잡는다.
    s5on: { roomType: ROOM_TYPES.standard,   dates: ['2026-09-12'] },
    s5off:{ roomType: ROOM_TYPES.standard,   dates: ['2026-09-13'] },
    // 혼합 지속. 전 타입 × 10일.
    s6:   { roomTypes: ALL_ROOM_TYPES,       dateRange: ['2026-09-21', '2026-09-30'] },
    // 조회 폭주 + 캐시 대조.
    s8:   { roomTypes: ALL_ROOM_TYPES,       dateRange: ['2026-10-01', '2026-10-10'] },
};

// F02 특가 시드 (V202). 9월 14~16일은 특가가 점유했으므로 일반 경합
// 시나리오(S1·S2·S5·S6)에 이 날짜를 쓰지 않는다. 같은 (객실타입, 날짜)는
// 같은 재고 행이라 서로의 결과를 오염시킨다.
//
// P1의 대상이 스탠다드(100실)인 이유가 중요하다.
//   20실 특가를 여는데 그날 일반 재고가 20 근처면, 8,000건이 몰릴 때 특가가
//   소진되기 전에 일반 재고가 먼저 바닥난다. 그러면 재는 것이 "특가 선착순
//   정확성"이 아니라 "일반 재고 고갈"로 조용히 바뀐다. 성공 20건이 나와도
//   그게 특가 제약 때문인지 재고 때문인지 구분할 수 없다.
//   100실이면 특가 20을 빼도 80이 남아 측정이 깨끗하다.
//
// S7의 부하 대상은 P1 하나다.
//   P2는 대상이 아니다. 판매 창을 벽시계 T+5분이 아니라 절대 날짜로 잡았기
//   때문이다. 그 판단이 옳다 — 오픈 시각을 실행 시각에 묶으면 시드가 부하테스트
//   실행 시점에 종속돼, 고정 날짜에서 얻은 재현성이 그 한 줄로 무너진다.
//   "닫혀 있다 열리는 순간"은 F02가 통합 테스트에서 Clock을 옮겨 재현한다.
//   스파이크의 본질은 오픈 순간이 아니라 한 재고 행에 요청이 한꺼번에 몰리는
//   것이고, 그건 이미 열린 P1에 램프업으로 충분히 만들어진다.
//   P3(이미 종료)는 판매 창 밖 거부를 보는 단건 확인용이지 부하 대상이 아니다.
export const PROMOTIONS = {
    p1: {
        roomType: ROOM_TYPES.standard, date: '2026-09-14', quantity: 20,
        price: 75000, window: '2026-08-01 ~ 2026-09-15', target: 'S7 스파이크',
    },
    p2: {
        roomType: ROOM_TYPES.standard, date: '2026-09-15', quantity: 20,
        price: 75000, window: '2026-09-01 ~ 2026-09-16', target: '부하 대상 아님',
    },
    p3: {
        roomType: ROOM_TYPES.deluxe, date: '2026-09-16', quantity: 10,
        price: 150000, window: '2026-08-01 ~ 2026-08-10 (종료)', target: '단건 확인',
    },
};

// 보조 시나리오. 체크인·노쇼는 날짜 조건(checkIn <= today < checkOut)이 걸려
// 있어 오늘 기준으로 잡아야 한다. F01 시드가 오늘을 범위 안에 넣어준 덕에
// 가능하다.
export const TODAY_BASED = {
    checkIn:  { checkIn: '2026-08-15', checkOut: '2026-08-17' },
    noShow:   { checkIn: '2026-08-14', checkOut: '2026-08-16' },
};

// 재고 행 자체가 없는 날짜. 409/404 경로 확인용.
export const OUT_OF_RANGE_DATE = '2026-10-30';

// ---------------------------------------------------------------------------
// 헬퍼
// ---------------------------------------------------------------------------

// 날짜 계산은 반드시 이 함수 하나만 쓴다 (scenarios.md §3-6).
// checkOut > checkIn을 보장해 400을 원천 차단한다.
export function nightsAfter(dateStr, nights) {
    const d = new Date(`${dateStr}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + nights);
    return d.toISOString().slice(0, 10);
}

// guestCount <= capacity × roomCount 를 위반하면 400이다.
// 스탠다드는 capacity=2라 여유가 거의 없다. 인원수는 이 과제의 경합 대상이
// 아니므로 400을 원천 차단하는 최솟값(1실당 1명)을 쓴다.
// 정원 검증 자체를 시험하고 싶으면 호출부에서 guestCount를 명시한다.
export function safeGuestCount(roomCount) {
    return roomCount;
}

export function reservationBody(roomType, checkInDate, opts = {}) {
    const roomCount = opts.roomCount || 1;
    const nights = opts.nights || 1;
    const body = {
        [FIELDS.roomTypeId]: roomType.id,
        [FIELDS.checkIn]: checkInDate,
        [FIELDS.checkOut]: nightsAfter(checkInDate, nights),
        [FIELDS.roomCount]: roomCount,
    };
    // D1이 기각되면 이 필드가 계약에서 사라진다.
    if (FEATURES.sendGuestCount) {
        body[FIELDS.guestCount] = opts.guestCount || safeGuestCount(roomCount);
    }
    return body;
}

export function headers(userId, idempotencyKey) {
    const h = { 'Content-Type': 'application/json', 'X-User-Id': userId };
    if (idempotencyKey) h['Idempotency-Key'] = idempotencyKey;
    return h;
}

// ---------------------------------------------------------------------------
// 사용자 식별자 — 함정 주의
// ---------------------------------------------------------------------------
//
// 사용자 테이블이 없다. 비어있지 않으면 아무 값이나 받는다. 그래서 오히려
// 두 가지를 스크립트가 직접 지켜야 한다.
//
// 1. 한 예약의 생성·확정·취소·체크인은 반드시 **같은 userId**로 보낸다.
//    취소가 소유자를 검증하는데, 남의 예약이면 403이 아니라 404를 준다
//    (확인번호의 존재 자체를 숨기는 설계다). VU 번호가 요청마다 바뀌면
//    취소가 전부 404로 떨어지는데, 404는 "예약이 없다"로 읽혀서 원인을
//    찾는 데 한참 걸린다.
//
// 2. 멱등 키는 (userId, idempotencyKey) 조합으로 저장된다. **같은 키
//    문자열이라도 userId가 다르면 서로 다른 요청으로 취급된다.**
//    멱등성 시나리오에서 재시도마다 VU가 바뀌면 키가 충돌하지 않아
//    멱등성을 전혀 시험하지 못한 채 전부 성공한다. 반드시 (사용자, 키)를
//    한 쌍으로 묶어 반복한다.
export function userId(n) {
    return `user-${n}`;
}
