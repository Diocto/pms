// T2 — 서버 응답을 경계에서 검증한다. 타입 단언(as)으로 믿지 않는다.
// 표본은 F01 스펙 2.2·2.3, F03 검색-API-계약 3절의 예시 그대로다.
import { describe, expect, it } from "vitest";
import {
  ContractViolation,
  parseAvailabilityResponse,
  parseErrorBody,
  parseReservationResponse,
} from "./contracts";

const availabilityOk = {
  hotelId: 1,
  checkIn: "2026-09-01",
  checkOut: "2026-09-04",
  nights: 3,
  guestCount: 2,
  roomCount: 1,
  searchedAt: "2026-09-01T14:03:22+09:00",
  source: "CACHE",
  staleToleranceSeconds: 10,
  items: [
    {
      roomTypeId: 1,
      roomTypeName: "스탠다드",
      capacity: 2,
      minRemaining: 96,
      pricePerNight: 150000,
      totalPrice: 450000,
    },
  ],
};

const reservationOk = {
  confirmationCode: "260901-H1R3-K7M2XQ4R",
  status: "PENDING",
  roomTypeId: 3,
  checkIn: "2026-09-01",
  checkOut: "2026-09-04",
  nights: 3,
  roomCount: 1,
  guestCount: 2,
  pricePerNight: 600000,
  totalPrice: 1800000,
  expiresAt: "2026-09-01T14:35:00",
};

describe("parseAvailabilityResponse", () => {
  it("계약 예시 그대로의 응답을 통과시킨다", () => {
    const r = parseAvailabilityResponse(availabilityOk);
    expect(r.items).toHaveLength(1);
    expect(r.items[0].minRemaining).toBe(96);
    expect(r.staleToleranceSeconds).toBe(10);
  });

  it("빈 결과는 emptyReason과 함께 통과시킨다", () => {
    const r = parseAvailabilityResponse({
      ...availabilityOk,
      items: [],
      emptyReason: "NOT_YET_OPEN",
      salesOpenUntil: "2026-10-29",
    });
    expect(r.emptyReason).toBe("NOT_YET_OPEN");
    expect(r.salesOpenUntil).toBe("2026-10-29");
  });

  it("모르는 emptyReason은 계약 위반이다 — 셋 중 하나여야 한다", () => {
    expect(() =>
      parseAvailabilityResponse({ ...availabilityOk, items: [], emptyReason: "WHO_KNOWS" }),
    ).toThrow(ContractViolation);
  });

  it("items가 배열이 아니면 계약 위반이다", () => {
    expect(() =>
      parseAvailabilityResponse({ ...availabilityOk, items: "none" }),
    ).toThrow(ContractViolation);
  });

  it("항목에 minRemaining이 없으면 계약 위반이다", () => {
    const broken = { ...availabilityOk, items: [{ roomTypeId: 1 }] };
    expect(() => parseAvailabilityResponse(broken)).toThrow(ContractViolation);
  });
});

describe("parseReservationResponse", () => {
  it("계약 예시 그대로의 201 본문을 통과시킨다", () => {
    const r = parseReservationResponse(reservationOk);
    expect(r.status).toBe("PENDING");
    expect(r.expiresAt).toBe("2026-09-01T14:35:00");
  });

  it("결제 거절 본문(status: CANCELLED + failureReason)을 통과시킨다", () => {
    const r = parseReservationResponse({
      confirmationCode: "260901-H1R3-K7M2XQ4R",
      status: "CANCELLED",
      failureReason: "PAYMENT_DECLINED",
    });
    expect(r.status).toBe("CANCELLED");
    expect(r.failureReason).toBe("PAYMENT_DECLINED");
  });

  it("모르는 status는 계약 위반이다 — 상태는 6종뿐이다", () => {
    expect(() =>
      parseReservationResponse({ ...reservationOk, status: "ON_HOLD" }),
    ).toThrow(ContractViolation);
  });

  it("confirmationCode가 없으면 계약 위반이다", () => {
    const { confirmationCode: _dropped, ...rest } = reservationOk;
    expect(() => parseReservationResponse(rest)).toThrow(ContractViolation);
  });
});

describe("parseErrorBody", () => {
  it("공통 ErrorResponse(code·message·traceId)를 읽는다", () => {
    const e = parseErrorBody({
      code: "INSUFFICIENT_INVENTORY",
      message: "남은 객실이 없습니다",
      traceId: "tr-8c31f2",
    });
    expect(e.code).toBe("INSUFFICIENT_INVENTORY");
    expect(e.traceId).toBe("tr-8c31f2");
  });

  it("형태가 어긋난 본문도 던지지 않고 UNKNOWN으로 감싼다 — 오류 처리 중의 오류는 최악이다", () => {
    const e = parseErrorBody("<html>Bad Gateway</html>");
    expect(e.code).toBe("UNKNOWN");
    expect(e.traceId).toBeUndefined();
  });
});
