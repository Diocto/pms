// T2 — 가짜 백엔드. fetch 경계에서 F01·F03 계약을 흉내 낸다.
// 완료 기준: 성공·실패 양쪽을 전환할 수 있다 (브리핑: "가짜를 만들 때 실패 응답도 함께").
import { beforeEach, describe, expect, it } from "vitest";
import { createApi } from "./api";
import { createMockBackend } from "./mock-backend";

const noSleep = () => Promise.resolve();

// 시각을 주입한다 — 만료 시나리오를 결정적으로 만들기 위해서다.
let nowMs: number;
let api: ReturnType<typeof createApi>;

beforeEach(() => {
  nowMs = Date.parse("2026-08-15T12:00:00+09:00");
  const mock = createMockBackend({ now: () => nowMs });
  api = createApi({ fetchLike: mock.fetchLike, sleep: noSleep });
});

const search = {
  hotelId: 1, checkIn: "2026-09-01", checkOut: "2026-09-04", guestCount: 2, roomCount: 1,
};
const book = {
  roomTypeId: 3, checkIn: "2026-09-01", checkOut: "2026-09-04", roomCount: 1, guestCount: 2,
};

describe("검색", () => {
  it("시드 그대로 — 서울 그랜드 호텔 3종, 스위트 잔여 10", async () => {
    const r = await api.searchAvailability(search);
    expect(r.items.map((i) => i.roomTypeName)).toEqual(["스탠다드", "디럭스", "스위트"]);
    expect(r.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("판매 기간(2026-10-29) 밖은 NOT_YET_OPEN + salesOpenUntil", async () => {
    const r = await api.searchAvailability({ ...search, checkIn: "2026-11-01", checkOut: "2026-11-03" });
    expect(r.items).toHaveLength(0);
    expect(r.emptyReason).toBe("NOT_YET_OPEN");
    expect(r.salesOpenUntil).toBe("2026-10-29");
  });

  it("인원 5명(객실 1)은 NO_FITTING_ROOM_TYPE — 최대 정원이 4다", async () => {
    const r = await api.searchAvailability({ ...search, guestCount: 5 });
    expect(r.emptyReason).toBe("NO_FITTING_ROOM_TYPE");
  });

  it("재고가 다 팔리면 SOLD_OUT", async () => {
    for (let i = 0; i < 10; i += 1) {
      await api.createReservation(book, { userId: `user-${i}`, idempotencyKey: `k-${i}` });
    }
    const r = await api.searchAvailability({ ...search, guestCount: 4 }); // 스위트만 맞는 조건
    expect(r.items).toHaveLength(0);
    expect(r.emptyReason).toBe("SOLD_OUT");
  });
});

describe("예약 생성", () => {
  it("생성하면 PENDING + 만료 시각(10분 뒤)이 오고 재고가 줄어든다", async () => {
    const r = await api.createReservation(book, { userId: "user-1001", idempotencyKey: "k-1" });
    expect(r.status).toBe("PENDING");
    expect(r.expiresAt).toBeDefined();
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9);
  });

  it("같은 멱등성 키 재요청은 같은 예약이 오고 재고는 한 번만 줄어든다", async () => {
    const a = await api.createReservation(book, { userId: "user-1001", idempotencyKey: "k-1" });
    const b = await api.createReservation(book, { userId: "user-1001", idempotencyKey: "k-1" });
    expect(b.confirmationCode).toBe(a.confirmationCode);
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9);
  });

  it("재고를 넘겨 예약하면 409 INSUFFICIENT_INVENTORY", async () => {
    for (let i = 0; i < 10; i += 1) {
      await api.createReservation(book, { userId: `user-${i}`, idempotencyKey: `k-${i}` });
    }
    await expect(
      api.createReservation(book, { userId: "user-x", idempotencyKey: "k-x" }),
    ).rejects.toMatchObject({ code: "INSUFFICIENT_INVENTORY", status: 409 });
  });

  it("정원 초과는 400 INVALID_REQUEST", async () => {
    await expect(
      api.createReservation({ ...book, guestCount: 5 }, { userId: "u", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST", status: 400 });
  });

  it("시연용: user-409는 항상 재고 부족, user-503은 항상 혼잡", async () => {
    await expect(
      api.createReservation(book, { userId: "user-409", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "INSUFFICIENT_INVENTORY" });
    await expect(
      api.createReservation(book, { userId: "user-503", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "LOCK_ACQUISITION_FAILED", status: 503 });
  });
});

describe("확정·취소·만료", () => {
  it("확정하면 CONFIRMED, 다시 확정해도 멱등 성공", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    const c1 = await api.confirmReservation(r.confirmationCode, "u");
    const c2 = await api.confirmReservation(r.confirmationCode, "u");
    expect(c1.status).toBe("CONFIRMED");
    expect(c2.status).toBe("CONFIRMED");
  });

  it("시연용: user-decline은 결제 거절 — 200 + CANCELLED + failureReason, 재고 복원", async () => {
    const r = await api.createReservation(book, { userId: "user-decline", idempotencyKey: "k" });
    const c = await api.confirmReservation(r.confirmationCode, "user-decline");
    expect(c.status).toBe("CANCELLED");
    expect(c.failureReason).toBe("PAYMENT_DECLINED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("취소하면 재고가 돌아오고, 재취소는 멱등 성공", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    await api.cancelReservation(r.confirmationCode, "u");
    const again = await api.cancelReservation(r.confirmationCode, "u");
    expect(again.status).toBe("CANCELLED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("10분이 지나면 조회 시 EXPIRED가 되고 재고가 돌아온다 (스케줄러 흉내)", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    nowMs += 11 * 60 * 1000;
    const g = await api.getReservation(r.confirmationCode, "u");
    expect(g.status).toBe("EXPIRED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("만료 뒤 확정 시도는 409 INVALID_STATE_TRANSITION", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    nowMs += 11 * 60 * 1000;
    await expect(api.confirmReservation(r.confirmationCode, "u")).rejects.toMatchObject({
      code: "INVALID_STATE_TRANSITION",
      status: 409,
    });
  });

  it("남의 예약은 403이 아니라 404다 — 존재를 숨긴다", async () => {
    const r = await api.createReservation(book, { userId: "u-mine", idempotencyKey: "k" });
    await expect(api.getReservation(r.confirmationCode, "u-other")).rejects.toMatchObject({
      code: "RESOURCE_NOT_FOUND",
      status: 404,
    });
  });
});
