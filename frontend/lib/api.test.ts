// T2 — api 클라이언트. fetch를 주입받아 가짜로 검증한다.
// vi.fn<typeof fetch>로 목을 선언해 mock.calls가 fetch 시그니처로 타입된다 — as 캐스트 금지.
import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi } from "./api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const reservationBody = {
  confirmationCode: "260901-H1R3-K7M2XQ4R",
  status: "PENDING",
  expiresAt: "2026-09-01T14:35:00",
};

const createParams = {
  roomTypeId: 3,
  checkIn: "2026-09-01",
  checkOut: "2026-09-04",
  roomCount: 1,
  guestCount: 2,
};

const noSleep = () => Promise.resolve();

function headerOf(call: Parameters<typeof fetch>, name: string): string | null {
  return new Headers(call[1]?.headers).get(name);
}

describe("createReservation", () => {
  it("X-User-Id와 Idempotency-Key 헤더가 나간다", async () => {
    const fetchLike = vi.fn<typeof fetch>(async () => jsonResponse(201, reservationBody));
    const api = createApi({ fetchLike, sleep: noSleep });
    await api.createReservation(createParams, { userId: "user-1001", idempotencyKey: "key-1" });

    expect(headerOf(fetchLike.mock.calls[0], "X-User-Id")).toBe("user-1001");
    expect(headerOf(fetchLike.mock.calls[0], "Idempotency-Key")).toBe("key-1");
  });

  it("201(신규)과 200(멱등 재요청) 모두 같은 형태로 돌아온다", async () => {
    const api201 = createApi({ fetchLike: async () => jsonResponse(201, reservationBody), sleep: noSleep });
    const api200 = createApi({ fetchLike: async () => jsonResponse(200, reservationBody), sleep: noSleep });
    const a = await api201.createReservation(createParams, { userId: "u", idempotencyKey: "k" });
    const b = await api200.createReservation(createParams, { userId: "u", idempotencyKey: "k" });
    expect(a.confirmationCode).toBe(b.confirmationCode);
  });

  it("REQUEST_IN_PROGRESS면 같은 키로 자동 재요청한다 — 재시도 최대 3회 = 총 4요청", async () => {
    let calls = 0;
    const fetchLike = vi.fn<typeof fetch>(async () => {
      calls += 1;
      if (calls < 4) return jsonResponse(409, { code: "REQUEST_IN_PROGRESS" });
      return jsonResponse(200, reservationBody);
    });
    const api = createApi({ fetchLike, sleep: noSleep });
    const r = await api.createReservation(createParams, { userId: "u", idempotencyKey: "k" });
    expect(r.status).toBe("PENDING");
    expect(calls).toBe(4);
    // 네 요청 모두 같은 멱등성 키였는지 — 키가 바뀌면 멱등성이 무의미해진다
    for (const call of fetchLike.mock.calls) {
      expect(headerOf(call, "Idempotency-Key")).toBe("k");
    }
  });

  it("재시도 3회가 전부 소진되면(총 4요청) 그 코드의 ApiError로 던진다", async () => {
    const fetchLike = vi.fn<typeof fetch>(async () => jsonResponse(409, { code: "REQUEST_IN_PROGRESS" }));
    const api = createApi({ fetchLike, sleep: noSleep });
    await expect(
      api.createReservation(createParams, { userId: "u", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "REQUEST_IN_PROGRESS" });
    expect(fetchLike).toHaveBeenCalledTimes(4);
  });

  it("409 INSUFFICIENT_INVENTORY는 재시도 없이 즉시 던진다 — 재시도 판단은 화면(4단계 흐름) 몫", async () => {
    const fetchLike = vi.fn<typeof fetch>(async () =>
      jsonResponse(409, { code: "INSUFFICIENT_INVENTORY", traceId: "tr-1" }),
    );
    const api = createApi({ fetchLike, sleep: noSleep });
    await expect(
      api.createReservation(createParams, { userId: "u", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "INSUFFICIENT_INVENTORY", status: 409, traceId: "tr-1" });
    expect(fetchLike).toHaveBeenCalledTimes(1);
  });

  it("JSON이 아닌 오류 본문(프록시 502 등)도 ApiError(UNKNOWN)로 감싼다", async () => {
    const fetchLike: typeof fetch = async () =>
      new Response("<html>Bad Gateway</html>", { status: 502, headers: { "content-type": "text/html" } });
    const api = createApi({ fetchLike, sleep: noSleep });
    await expect(
      api.createReservation(createParams, { userId: "u", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "UNKNOWN", status: 502 });
  });
});

describe("searchAvailability", () => {
  it("쿼리를 조립하고 fresh=true를 붙일 수 있다", async () => {
    const fetchLike = vi.fn<typeof fetch>(async () =>
      jsonResponse(200, {
        hotelId: 1, checkIn: "2026-09-01", checkOut: "2026-09-04", nights: 3,
        guestCount: 2, roomCount: 1, searchedAt: "t", staleToleranceSeconds: 10, items: [],
        emptyReason: "SOLD_OUT",
      }),
    );
    const api = createApi({ fetchLike, sleep: noSleep });
    await api.searchAvailability(
      { hotelId: 1, checkIn: "2026-09-01", checkOut: "2026-09-04", guestCount: 2, roomCount: 1 },
      { fresh: true },
    );
    const url = String(fetchLike.mock.calls[0][0]);
    expect(url).toContain("/api/availability?");
    expect(url).toContain("hotelId=1");
    expect(url).toContain("fresh=true");
  });
});

describe("getReservation / confirm / cancel", () => {
  it("확인번호를 경로에 넣고 X-User-Id를 보낸다", async () => {
    const fetchLike = vi.fn<typeof fetch>(async () => jsonResponse(200, reservationBody));
    const api = createApi({ fetchLike, sleep: noSleep });
    await api.getReservation("260901-H1R3-K7M2XQ4R", "user-1001");
    await api.confirmReservation("260901-H1R3-K7M2XQ4R", "user-1001");
    await api.cancelReservation("260901-H1R3-K7M2XQ4R", "user-1001");
    const urls = fetchLike.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).toContain("/api/reservations/260901-H1R3-K7M2XQ4R");
    expect(urls[1]).toContain("/confirm");
    expect(urls[2]).toContain("/cancel");
  });

  it("confirm의 200 + CANCELLED(결제 거절)는 예외가 아니라 정상 반환이다", async () => {
    const fetchLike: typeof fetch = async () =>
      jsonResponse(200, {
        confirmationCode: "260901-H1R3-K7M2XQ4R",
        status: "CANCELLED",
        failureReason: "PAYMENT_DECLINED",
      });
    const api = createApi({ fetchLike, sleep: noSleep });
    const r = await api.confirmReservation("260901-H1R3-K7M2XQ4R", "u");
    expect(r.status).toBe("CANCELLED");
    expect(r.failureReason).toBe("PAYMENT_DECLINED");
  });
});

describe("ApiError", () => {
  it("code·status·traceId를 들고 다닌다", () => {
    const e = new ApiError(409, "INSUFFICIENT_INVENTORY", "tr-9");
    expect(e.status).toBe(409);
    expect(e.code).toBe("INSUFFICIENT_INVENTORY");
    expect(e.traceId).toBe("tr-9");
  });
});
