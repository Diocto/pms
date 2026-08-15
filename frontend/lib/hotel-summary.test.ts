// 검색 개선(관리자 지시 2026-08-16) — 호텔 목록 카드의 요약 계산.
// 검색 API는 hotelId 필수라 호텔 목록은 호텔별 응답 2개를 조립해 만든다.
import { describe, expect, it } from "vitest";
import { summarizeHotel } from "./hotel-summary";
import type { AvailabilityResponse } from "./contracts";

function res(partial: Partial<AvailabilityResponse>): AvailabilityResponse {
  return {
    hotelId: 1, checkIn: "2026-09-01", checkOut: "2026-09-04", nights: 3,
    guestCount: 2, roomCount: 1, searchedAt: "t", staleToleranceSeconds: 10,
    items: [], ...partial,
  };
}

const item = (roomTypeId: number, totalPrice: number, minRemaining = 10) => ({
  roomTypeId, roomTypeName: `타입${roomTypeId}`, capacity: 2, minRemaining,
  pricePerNight: totalPrice / 3, totalPrice,
});

describe("summarizeHotel", () => {
  it("예약 가능하면 객실 종 수와 최저 총액을 요약한다", () => {
    const s = summarizeHotel(res({ items: [item(1, 450000), item(2, 750000)] }));
    expect(s).toEqual({ kind: "available", roomTypeCount: 2, minTotalPrice: 450000 });
  });

  it("빈 결과는 emptyReason을 그대로 종류로 넘긴다 — 매진과 판매 전은 다른 정보다", () => {
    expect(summarizeHotel(res({ emptyReason: "SOLD_OUT" }))).toEqual({ kind: "SOLD_OUT" });
    expect(summarizeHotel(res({ emptyReason: "NOT_YET_OPEN" }))).toEqual({ kind: "NOT_YET_OPEN" });
    expect(summarizeHotel(res({ emptyReason: "NO_FITTING_ROOM_TYPE" }))).toEqual({
      kind: "NO_FITTING_ROOM_TYPE",
    });
  });

  it("빈 결과인데 emptyReason이 없으면 매진으로 다룬다 — 서버 판단 부재 시 보수적으로", () => {
    expect(summarizeHotel(res({}))).toEqual({ kind: "SOLD_OUT" });
  });
});
