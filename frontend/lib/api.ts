// API 호출은 전부 이 모듈을 거친다. 컴포넌트에 fetch를 흩뿌리지 않는다.
//
// - 응답은 contracts.ts의 parse 함수로 경계에서 검증한다.
// - 오류는 ApiError(code·status·traceId) 하나로 통일한다. 문구 변환은 error-messages.ts.
// - REQUEST_IN_PROGRESS만 이 계층이 같은 키로 자동 재요청한다(최대 3회) — 이건 "잠시 뒤
//   같은 키로 재요청"이 계약이 정한 올바른 반응이라서다. 409 INSUFFICIENT_INVENTORY의
//   재시도는 재검색과 얽힌 화면 흐름(시안 S2 상태 3)이므로 여기서 하지 않는다.

import {
  ERROR_CODES,
  parseAvailabilityResponse,
  parseErrorBody,
  parseReservationResponse,
  type AvailabilityResponse,
  type ReservationResponse,
} from "./contracts";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly traceId?: string,
    serverMessage?: string,
  ) {
    super(serverMessage ?? code);
    this.name = "ApiError";
  }
}

export interface SearchParams {
  hotelId: number;
  checkIn: string;
  checkOut: string;
  guestCount: number;
  roomCount: number;
}

export interface CreateReservationParams {
  roomTypeId: number;
  checkIn: string;
  checkOut: string;
  roomCount: number;
  guestCount: number;
}

interface ApiDeps {
  fetchLike?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  baseUrl?: string;
}

const IN_PROGRESS_MAX_ATTEMPTS = 3;
const IN_PROGRESS_WAIT_MS = 1000;

export function createApi(deps: ApiDeps = {}) {
  const fetchLike = deps.fetchLike ?? fetch;
  const sleep = deps.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const base = deps.baseUrl ?? "";

  async function readJson(res: Response): Promise<unknown> {
    try {
      return await res.json();
    } catch {
      return undefined; // JSON이 아니면(프록시 오류 페이지 등) UNKNOWN으로 감싼다
    }
  }

  async function throwApiError(res: Response): Promise<never> {
    const body = parseErrorBody(await readJson(res));
    throw new ApiError(res.status, body.code, body.traceId, body.message);
  }

  async function searchAvailability(
    params: SearchParams,
    opts: { fresh?: boolean } = {},
  ): Promise<AvailabilityResponse> {
    const q = new URLSearchParams({
      hotelId: String(params.hotelId),
      checkIn: params.checkIn,
      checkOut: params.checkOut,
      guestCount: String(params.guestCount),
      roomCount: String(params.roomCount),
    });
    if (opts.fresh) q.set("fresh", "true");
    const res = await fetchLike(`${base}/api/availability?${q}`);
    if (!res.ok) await throwApiError(res);
    return parseAvailabilityResponse(await res.json());
  }

  async function createReservation(
    params: CreateReservationParams,
    opts: { userId: string; idempotencyKey: string },
  ): Promise<ReservationResponse> {
    for (let attempt = 1; ; attempt += 1) {
      const res = await fetchLike(`${base}/api/reservations`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-User-Id": opts.userId,
          "Idempotency-Key": opts.idempotencyKey,
        },
        body: JSON.stringify(params),
      });
      if (res.ok) return parseReservationResponse(await res.json());

      const body = parseErrorBody(await readJson(res));
      const inProgress = res.status === 409 && body.code === ERROR_CODES.REQUEST_IN_PROGRESS;
      if (inProgress && attempt < IN_PROGRESS_MAX_ATTEMPTS) {
        await sleep(IN_PROGRESS_WAIT_MS);
        continue; // 같은 멱등성 키로 다시 — 키를 바꾸면 멱등성이 무의미해진다
      }
      throw new ApiError(res.status, body.code, body.traceId, body.message);
    }
  }

  async function reservationAction(
    code: string,
    userId: string,
    action?: "confirm" | "cancel",
  ): Promise<ReservationResponse> {
    const path = `${base}/api/reservations/${encodeURIComponent(code)}${action ? `/${action}` : ""}`;
    const res = await fetchLike(path, {
      method: action ? "POST" : "GET",
      headers: { "X-User-Id": userId },
    });
    if (!res.ok) await throwApiError(res);
    // 결제 거절도 200 + status: CANCELLED로 온다 — 예외가 아니라 정상 반환이다.
    return parseReservationResponse(await res.json());
  }

  return {
    searchAvailability,
    createReservation,
    getReservation: (code: string, userId: string) => reservationAction(code, userId),
    confirmReservation: (code: string, userId: string) => reservationAction(code, userId, "confirm"),
    cancelReservation: (code: string, userId: string) => reservationAction(code, userId, "cancel"),
  };
}

export type Api = ReturnType<typeof createApi>;
