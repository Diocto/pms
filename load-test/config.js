// F04 부하테스트 — 단일 진실 지점(single source of truth)
//
// API 계약이 바뀌면 이 파일만 고친다. 시나리오 스크립트는 여기서만 값을 가져간다.
//
// 근거: docs/load-test/scenarios.md §6 (F01 계약·시드 확정본, 2026-08-15)

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

// ---------------------------------------------------------------------------
// 승인 리스크 스위치 — 전부 없앴다 (2026-08-15)
// ---------------------------------------------------------------------------
//
// F01의 [필수] 결정 셋이 승인 전이라 기각 대비 플래그로 격리해뒀었다.
// 셋 다 판단이 끝났으므로 플래그를 전부 제거했다.
//
//   D7 confirmationCode -> **채택.** 경로는 코드 기반으로 확정
//   D1 guestCount       -> **채택.** 요청 본문에 항상 싣는다
//   D4 NO_SHOW          -> **유예(추후 작업).** 이번 범위에 없다
//
// 대비책은 값을 냈다. D4가 빠질 때 플래그로 격리해둔 덕에 반영이 표 정의
// 한 곳 수정으로 끝났다. 그래도 플래그는 남기지 않는다 — 다시 뒤집힐 일이
// 없는 스위치를 두면 읽는 사람이 "언젠가 켜지는 기능"으로 오해한다.

// ---------------------------------------------------------------------------
// 엔드포인트 — 계약 확정본
// ---------------------------------------------------------------------------

export const PATHS = {
    create: '/api/reservations',
    expire: '/api/internal/reservations/expire',
    // 2026-08-15 확인: app/main.py 에 실제로 있는 경로다 (actuator 는 없다).
    health: '/health',
    // F03 검색. X-User-Id를 요구하지 않는다 (F03 스펙 D11).
    availability: '/api/availability',
};

// F02 특가에는 전용 경로가 없다. 확정 계약은 일반 예약 경로(create)에
// discounts 배열을 실어 보내는 방식이다. 초기 설계에 있던
// /api/promotions/{roomTypeId}/{stayDate} 헬퍼는 계약이 뒤집히면서 삭제했다.
// 남겨두면 "특가 전용 경로가 있다"는 잘못된 단서가 된다.

// 예약 식별자를 경로로 바꾸는 유일한 함수.
export function pathFor(ref, action) {
    const base = `/api/reservations/${ref}`;
    return action ? `${base}/${action}` : base;
}

// 확인번호 형식: 260901-H1R3-K7M2XQ4R (20자, 체크인 yyMMdd + 호텔/객실타입 + 무작위 8자)
//
// **이 코드를 절대 파싱하지 않는다.** 형식에서 날짜나 객실타입을 뽑아 쓰고
// 싶어질 수 있지만(예: 시나리오별 필터링) 하지 않는다. 이유 둘:
//
//   1. 관리자 제약이 "key 포맷에 의한 로직은 넣지 말자"다. F01은 만드는
//      함수만 두고 읽는 함수를 두지 않았으며, 타입도 CHAR가 아니라 VARCHAR다
//      (길이에 기대지 않겠다는 선언). 부하 스크립트가 파싱하면 그 규칙을
//      우회하는 셈이다.
//   2. 형식이 또 바뀌면 조용히 깨진다. 지금 이 주석의 예시도 그때 거짓말이 된다.
//
// 필요한 값은 전부 응답 본문의 필드에서 읽는다. 길이도 가정하지 않는다.
export function idField() {
    return 'confirmationCode';
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
    // 할인 자리. 특가 예약은 **별도 엔드포인트가 아니라** 이 필드를 실어
    // 같은 POST /api/reservations 로 보낸다.
    // 0개 또는 1개. 2개 이상이면 400이다.
    discounts: 'discounts',
};

// 부하 프로파일에서 조절하는 앱 설정 키.
// 스크립트가 직접 쓰지는 않지만, 어느 회차에 무엇을 바꿨는지 기록에 남기려고
// 여기 모아둔다. 리포트 §2의 표와 일치시킨다.
//
// **이름은 조작자가 셸에 그대로 치는 환경변수 이름이다.** 스택 전환(2026-08-15)
// 이후 표기를 이렇게 제안했다 — 리포트를 보고 재현하는 사람이 그대로 붙여넣을
// 수 있어야 하기 때문이다. 실제 철자는 F01·F02가 확정한다.
// 2026-08-15에 app/common/config.py 를 직접 읽고 맞춘 목록이다.
// 그 파일의 validation_alias 가 계약이고, 조작자가 셸에 치는 이름과 같다.
export const APP_SETTINGS = {
    lockEnabled: 'PMS_LOCK_ENABLED',                       // S5 대조
    holdMinutes: 'PMS_RESERVATION_HOLD_MINUTES',           // S4-B에서 1로
    declineRate: 'PMS_PAYMENT_DECLINE_RATE',               // 경합 0.0 / 결제 분기 1.0
    searchCacheEnabled: 'PMS_SEARCH_CACHE_ENABLED',        // S8 대조 (F03가 추가)
    // S7-C 대조. 실제 키 이름은 F02가 정한다. 병합 후 대조할 것.
    promotionGateEnabled: 'PMS_PROMOTION_GATE_ENABLED',
};

// **바꾸지는 않지만 반드시 기록하는 설정.**
//
// 위 APP_SETTINGS 는 우리가 회차마다 손대는 스위치고, 아래 셋은 손대지 않되
// 값이 결과를 좌우하는 것들이다. 리포트에 안 적으면 재현이 안 된다.
//
//   PMS_LOCK_WAIT_MILLIS (기본 200)
//     락을 얼마나 기다렸다 포기하는가. **S5-ON 의 락 실패 건수는 사실상 이
//     값이 정한다.** 200ms 는 짧은 편이라 경합이 심하면 실패가 많이 나오는데,
//     그건 락 설계가 나쁜 게 아니라 이 값이 그렇게 정해진 것이다.
//     "락의 가격"을 말할 때 이 숫자를 같이 대지 않으면 근거가 아니다.
//
//   PMS_LOCK_TTL_SECONDS (기본 3)
//     락을 자동으로 놓는 시간. **트랜잭션이 3초를 넘기면 내가 쥔 락이 남에게
//     넘어간다.** 그때 redis-py 가 LockNotOwnedError 를 던지고, 그 순간
//     임계 구역에 둘이 들어가 있었다는 뜻이 된다. 정상 동작에서는 안 나와야
//     한다. 로그 관찰 항목이다 (scenarios.md §3-11).
//
//   PMS_RESERVATION_EXPIRE_SCAN_SECONDS (기본 30)
//     만료 스캔 주기. S4-B 가 hold 를 1분으로 줄여도 만료는 정확히 1분에
//     일어나지 않고 **그 뒤 첫 스캔 시점**에 일어난다. 대기 시간을 이 값까지
//     더해서 잡지 않으면 "만료 0건"으로 끝난다.
export const OBSERVED_SETTINGS = {
    lockWaitMillis: 'PMS_LOCK_WAIT_MILLIS',
    lockTtlSeconds: 'PMS_LOCK_TTL_SECONDS',
    expireScanSeconds: 'PMS_RESERVATION_EXPIRE_SCAN_SECONDS',
};

// 특가 예약에 실을 할인 항목.
// reference(프로모션 식별자)의 실제 값은 F02 V202 시드가 정한다.
// **병합 후 채운다. 지금은 자리만 만든다.**
export const PROMOTION_REFERENCE = __ENV.PROMOTION_REF || 'TODO-F02-V202';

export function promotionDiscount(reference) {
    return [{ type: 'PROMOTION', reference: reference || PROMOTION_REFERENCE }];
}

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
};

// 재고를 점유하지 않는 종료 상태. 보존식의 "활성 예약"에서 제외된다.
// CHECKED_IN·CHECKED_OUT은 실제로 묵은 것이므로 점유를 유지한다.
export const RELEASED_STATUSES = [STATUS.CANCELLED, STATUS.EXPIRED];

// ---------------------------------------------------------------------------
// 전이 표 36칸 = 허용 전이 7 + 멱등 성공 6 + 거부 23
// ---------------------------------------------------------------------------
//
// 상태 6개 x 이벤트 6개. F01 D4(NO_SHOW) 유예로 49칸에서 줄었다 (2026-08-15).
//
// 멱등 성공 6칸: 상태가 안 바뀌고 200이 나가는 조합이다.
//
// 판정 규칙이 이 표 덕에 단순해진다:
//   **200을 받았다면 허용 전이 7칸이거나 아래 6칸 중 하나여야 한다.**
//   나머지 23칸에서 200이 나오면 금지 전이가 통과한 것이므로 즉시 실패다.
export const IDEMPOTENT_CELLS = [
    [STATUS.CONFIRMED,   'CONFIRM'],
    [STATUS.CANCELLED,   'CANCEL'],
    [STATUS.CANCELLED,   'PAYMENT_FAILED'],
    [STATUS.EXPIRED,     'EXPIRE'],
    [STATUS.CHECKED_IN,  'CHECK_IN'],
    [STATUS.CHECKED_OUT, 'CHECK_OUT'],
].map(([state, event]) => `${state}:${event}`);

// 허용 전이 7칸. (현재 상태, 이벤트) -> 다음 상태
//
// CONFIRMED에서 자동으로 빠져나가는 출구가 없다. D4 유예의 결과이며,
// 노쇼 손님의 예약은 운영자가 수동 취소해야 한다. F01이 이 구멍을
// 제출 문서에 절단 근거와 함께 명시했다. 리포트에서 "전이 완결성"을
// 주장할 때 이 예외를 반드시 함께 적는다.
export const ALLOWED_TRANSITIONS = {
    'PENDING:CONFIRM':          STATUS.CONFIRMED,
    'PENDING:PAYMENT_FAILED':   STATUS.CANCELLED,
    'PENDING:CANCEL':           STATUS.CANCELLED,
    'PENDING:EXPIRE':           STATUS.EXPIRED,
    'CONFIRMED:CANCEL':         STATUS.CANCELLED,
    'CONFIRMED:CHECK_IN':       STATUS.CHECKED_IN,
    'CHECKED_IN:CHECK_OUT':     STATUS.CHECKED_OUT,
};

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
    return false; // 거부 23칸에서 200이 나왔다 -> 금지 전이 통과
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
// promoPrice: 실제로 청구되는 특가 단가. reservation.price_per_night 에
//   이 값이 기록되므로 **금액 불변식을 DB로 검증할 수 있다.**
//   특가 사용권이 발급된 예약에 정가가 박혀 있으면 그건 사용자가 요청하지
//   않은 금액을 청구한 것이다.
export const PROMOTIONS = {
    p1: {
        roomType: ROOM_TYPES.standard, date: '2026-09-14', quantity: 20,
        promoPrice: 75000, listPrice: 150000,
        window: '2026-08-01 ~ 2026-09-15', target: 'S7 스파이크',
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

// 보조 시나리오. 체크인은 날짜 조건(checkIn <= today < checkOut)이 걸려
// 있어 오늘 기준으로 잡아야 한다. F01 시드가 오늘을 범위 안에 넣어준 덕에
// 가능하다.
//
// D4 유예 이후 체크인 상한(today < checkOut)의 비중이 커졌다.
// 노쇼 스케줄러가 없어져, 기간이 지난 예약의 체크인을 막는 유일한 장치가 됐다.
// S6의 과거 체크아웃 프로브가 그 상한을 때리는 유일한 검증이다.
export const TODAY_BASED = {
    checkIn:  { checkIn: '2026-08-15', checkOut: '2026-08-17' },
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
    // D1 채택으로 확정 필드다. 항상 싣는다.
    body[FIELDS.guestCount] = opts.guestCount || safeGuestCount(roomCount);
    // 일반 예약은 discounts를 아예 보내지 않는다. S1~S6·S8이 여기 해당한다.
    if (opts.discounts) {
        body[FIELDS.discounts] = opts.discounts;
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
