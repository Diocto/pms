// 백엔드 계약의 사본 — 최종 진실은 F01이 완성한 Swagger(/openapi.json)다 (관리자 지시).
// 그 전까지는 F01 스펙 2장·F03 검색-API-계약 문서에서 읽었다.
// 계약이 바뀌면 이 파일 하나만 고친다. 화면은 여기서 나간 타입·상수만 본다 —
// 필드 이름과 에러 코드 문자열이 이 파일 밖에 직접 나타나면 안 된다.
//
// 서버 응답은 타입 단언(as)으로 믿지 않고 이 파일의 parse 함수로 실제 검증한다.
// 형태가 어긋나면 ContractViolation — 화면에서는 일반 오류로 떨어진다.
//
// ── 가정 대장 — Swagger가 나오면 아래 [가정]만 확인하면 된다 ─────────────────
// [문서] 에러 코드 7종, 에러 본문 {code,message,traceId} (F01 2.1 에러 코드 계약)
// [문서] 검색 응답 필드·emptyReason 3종·salesOpenUntil (F03 계약 3절)
// [문서] 예약 생성 201 본문 필드 전부 (F01 2.2 응답 예시)
// [문서] confirm 200 본문: status CONFIRMED+confirmedAt / CANCELLED+failureReason (F01 2.3)
// [확인됨 2026-08-16, 실 백엔드 대조] GET·confirm·cancel·check-in/out 전부 생성 201과
//        같은 response_model(ReservationResponse, camelCase). 스키마·실호출로 검증.
//        nights 필드는 응답에 없다(파서에서 선택 필드 — 화면은 날짜로 계산). createdAt 추가됨(미사용).
// [확인됨 2026-08-16] 날짜시각은 오프셋 없는 로컬(Asia/Seoul) — expiresAt 실측 일치.
// [확인됨 2026-08-16] 에러 본문 {code, message, traceId} camelCase — 400 실호출로 검증.
// [확인됨 2026-08-16] 멱등 재요청은 200(최초 201과 상태 코드로 구분) — 라우터 D18 확인.
// [가정] 검색 응답의 source 필드 존재(화면 미사용·타입에서 제외) — 대조만 하면 된다.
// [확인 예정] 공용 설정 노출 계약 이름 ConfigReport→RuntimeReport (화면 무관, PM 공지)
// [해소됨] 검색 경로 — F03이 구두 오기였다고 정정 (2026-08-16). 계약 문서의
//        GET /api/availability?hotelId= 그대로 간다. 코드 변경 없음.
//        (같은 대화에서 emptyReason을 "NO_INVENTORY"로 쓴 오기도 있었다 — 계약 문서의
//        NO_FITTING_ROOM_TYPE이 진실. F03에 통지함. Swagger 대조 때 이 값도 재확인.)
// [실물 확인됨] 시드 호텔 1=서울 그랜드, 2=부산 오션뷰 (origin/main 051 리비전 대조,
//        lib/hotels.ts 상수와 일치. 호텔 목록 API는 만들지 않기로 F03과 합의 — 시안 D7)

// 에러 코드 상수 — 화면·흐름 코드는 문자열 대신 반드시 이걸 쓴다.
export const ERROR_CODES = {
  INVALID_REQUEST: "INVALID_REQUEST",
  RESOURCE_NOT_FOUND: "RESOURCE_NOT_FOUND",
  INVALID_STATE_TRANSITION: "INVALID_STATE_TRANSITION",
  INSUFFICIENT_INVENTORY: "INSUFFICIENT_INVENTORY",
  REQUEST_IN_PROGRESS: "REQUEST_IN_PROGRESS",
  LOCK_ACQUISITION_FAILED: "LOCK_ACQUISITION_FAILED",
  INTERNAL_ERROR: "INTERNAL_ERROR",
} as const;

export type ErrorCode = keyof typeof ERROR_CODES;

// 계약 밖 상황(파싱 불가 본문 등)을 나타내는 프론트 내부 값. 계약 7종이 아니다.
export const UNKNOWN_CODE = "UNKNOWN";

export type ReservationStatus =
  | "PENDING"
  | "CONFIRMED"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "CANCELLED"
  | "EXPIRED";

const RESERVATION_STATUSES: ReadonlySet<string> = new Set([
  "PENDING",
  "CONFIRMED",
  "CHECKED_IN",
  "CHECKED_OUT",
  "CANCELLED",
  "EXPIRED",
]);

export type EmptyReason = "SOLD_OUT" | "NOT_YET_OPEN" | "NO_FITTING_ROOM_TYPE";

const EMPTY_REASONS: ReadonlySet<string> = new Set([
  "SOLD_OUT",
  "NOT_YET_OPEN",
  "NO_FITTING_ROOM_TYPE",
]);

export interface AvailabilityItem {
  roomTypeId: number;
  roomTypeName: string;
  capacity: number;
  minRemaining: number;
  pricePerNight: number;
  totalPrice: number;
}

export interface AvailabilityResponse {
  hotelId: number;
  checkIn: string;
  checkOut: string;
  nights: number;
  guestCount: number;
  roomCount: number;
  searchedAt: string;
  // source(CACHE/DB)는 계약에 있지만 화면에 노출하지 않으므로(PM 지시) 타입에서 뺀다.
  staleToleranceSeconds: number;
  items: AvailabilityItem[];
  emptyReason?: EmptyReason;
  salesOpenUntil?: string;
}

export interface ReservationResponse {
  confirmationCode: string;
  status: ReservationStatus;
  roomTypeId?: number;
  checkIn?: string;
  checkOut?: string;
  nights?: number;
  roomCount?: number;
  guestCount?: number;
  pricePerNight?: number;
  totalPrice?: number;
  expiresAt?: string;
  confirmedAt?: string;
  terminatedAt?: string;
  failureReason?: string;
}

export interface ErrorBody {
  code: string; // 계약 7종 + 방어용 "UNKNOWN"
  message?: string;
  traceId?: string;
}

export class ContractViolation extends Error {
  constructor(what: string) {
    super(`서버 응답이 계약과 다릅니다: ${what}`);
    this.name = "ContractViolation";
  }
}

// ---- 좁히기 도우미 ----
// 검증과 좁히기를 타입 가드로 묶는다 — 검증 줄을 지우면 좁히기도 같이 죽는다 (as 캐스트 금지)

function isEmptyReason(v: string): v is EmptyReason {
  return EMPTY_REASONS.has(v);
}

function isReservationStatus(v: string): v is ReservationStatus {
  return RESERVATION_STATUSES.has(v);
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(o: Record<string, unknown>, key: string): number {
  const v = o[key];
  if (typeof v !== "number" || !Number.isFinite(v)) throw new ContractViolation(`${key}가 숫자가 아님`);
  return v;
}

function str(o: Record<string, unknown>, key: string): string {
  const v = o[key];
  if (typeof v !== "string" || v.length === 0) throw new ContractViolation(`${key}가 문자열이 아님`);
  return v;
}

function optStr(o: Record<string, unknown>, key: string): string | undefined {
  const v = o[key];
  if (v === undefined || v === null) return undefined;
  if (typeof v !== "string") throw new ContractViolation(`${key}가 문자열이 아님`);
  return v;
}

function optNum(o: Record<string, unknown>, key: string): number | undefined {
  const v = o[key];
  if (v === undefined || v === null) return undefined;
  if (typeof v !== "number" || !Number.isFinite(v)) throw new ContractViolation(`${key}가 숫자가 아님`);
  return v;
}

// ---- parse 함수 ----

export function parseAvailabilityResponse(raw: unknown): AvailabilityResponse {
  if (!isRecord(raw)) throw new ContractViolation("본문이 객체가 아님");
  const itemsRaw = raw.items;
  if (!Array.isArray(itemsRaw)) throw new ContractViolation("items가 배열이 아님");

  const items: AvailabilityItem[] = itemsRaw.map((it, i) => {
    if (!isRecord(it)) throw new ContractViolation(`items[${i}]가 객체가 아님`);
    return {
      roomTypeId: num(it, "roomTypeId"),
      roomTypeName: str(it, "roomTypeName"),
      capacity: num(it, "capacity"),
      minRemaining: num(it, "minRemaining"),
      pricePerNight: num(it, "pricePerNight"),
      totalPrice: num(it, "totalPrice"),
    };
  });

  let emptyReason: EmptyReason | undefined;
  if (raw.emptyReason !== undefined && raw.emptyReason !== null) {
    const reason = raw.emptyReason;
    if (typeof reason !== "string" || !isEmptyReason(reason))
      throw new ContractViolation(`emptyReason 값이 계약 밖: ${String(reason)}`);
    emptyReason = reason;
  }

  return {
    hotelId: num(raw, "hotelId"),
    checkIn: str(raw, "checkIn"),
    checkOut: str(raw, "checkOut"),
    nights: num(raw, "nights"),
    guestCount: num(raw, "guestCount"),
    roomCount: num(raw, "roomCount"),
    searchedAt: str(raw, "searchedAt"),
    staleToleranceSeconds: num(raw, "staleToleranceSeconds"),
    items,
    emptyReason,
    salesOpenUntil: optStr(raw, "salesOpenUntil"),
  };
}

export function parseReservationResponse(raw: unknown): ReservationResponse {
  if (!isRecord(raw)) throw new ContractViolation("본문이 객체가 아님");
  const status = str(raw, "status");
  if (!isReservationStatus(status))
    throw new ContractViolation(`status 값이 계약 밖: ${status}`);

  return {
    confirmationCode: str(raw, "confirmationCode"),
    status,
    roomTypeId: optNum(raw, "roomTypeId"),
    checkIn: optStr(raw, "checkIn"),
    checkOut: optStr(raw, "checkOut"),
    nights: optNum(raw, "nights"),
    roomCount: optNum(raw, "roomCount"),
    guestCount: optNum(raw, "guestCount"),
    pricePerNight: optNum(raw, "pricePerNight"),
    totalPrice: optNum(raw, "totalPrice"),
    expiresAt: optStr(raw, "expiresAt"),
    confirmedAt: optStr(raw, "confirmedAt"),
    terminatedAt: optStr(raw, "terminatedAt"),
    failureReason: optStr(raw, "failureReason"),
  };
}

// 오류 본문 해석은 절대 던지지 않는다. 오류 처리 중의 오류는 최악이다.
export function parseErrorBody(raw: unknown): ErrorBody {
  if (isRecord(raw) && typeof raw.code === "string" && raw.code.length > 0) {
    return {
      code: raw.code,
      message: typeof raw.message === "string" ? raw.message : undefined,
      traceId: typeof raw.traceId === "string" ? raw.traceId : undefined,
    };
  }
  return { code: UNKNOWN_CODE };
}
