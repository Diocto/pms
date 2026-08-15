// 백엔드 계약의 사본 — 진실은 F01 스펙 2장, F03 검색-API-계약이다.
// 계약이 바뀌면 이 파일 하나만 고친다. 화면은 여기서 나간 타입만 본다.
//
// 서버 응답은 타입 단언(as)으로 믿지 않고 이 파일의 parse 함수로 실제 검증한다.
// 형태가 어긋나면 ContractViolation — 화면에서는 일반 오류로 떨어진다.

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

function isRecord(v: unknown): v is Record<string, unknown> {
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
    if (typeof reason !== "string" || !EMPTY_REASONS.has(reason))
      throw new ContractViolation(`emptyReason 값이 계약 밖: ${String(reason)}`);
    emptyReason = reason as EmptyReason;
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
  if (!RESERVATION_STATUSES.has(status))
    throw new ContractViolation(`status 값이 계약 밖: ${status}`);

  return {
    confirmationCode: str(raw, "confirmationCode"),
    status: status as ReservationStatus,
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
  return { code: "UNKNOWN" };
}
