// 날짜 유틸 — UTC 순수 산술이라 실행 타임존과 무관해야 한다.
import { describe, expect, it } from "vitest";
import { addDays, clampStayFrom, nightsBetween } from "./dates";

describe("addDays", () => {
  it("월·연 경계를 넘는다", () => {
    expect(addDays("2026-10-29", 1)).toBe("2026-10-30");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-09-01", -1)).toBe("2026-08-31");
  });
});

describe("nightsBetween", () => {
  it("체크아웃 당일은 세지 않는다", () => {
    expect(nightsBetween("2026-09-01", "2026-09-04")).toBe(3);
    expect(nightsBetween("2026-09-01", "2026-09-02")).toBe(1);
  });
});

describe("clampStayFrom — 재예약 날짜 보정 (라운드3)", () => {
  const TODAY = "2026-08-15";

  it("미래 예약은 그대로 둔다", () => {
    expect(clampStayFrom(TODAY, "2026-09-01", "2026-09-04")).toEqual({
      checkIn: "2026-09-01",
      checkOut: "2026-09-04",
    });
  });

  it("진행 중 투숙(checkIn 과거)은 checkIn만 오늘로 당긴다", () => {
    expect(clampStayFrom(TODAY, "2026-08-14", "2026-08-17")).toEqual({
      checkIn: "2026-08-15",
      checkOut: "2026-08-17",
    });
  });

  it("이미 끝난 숙박은 오늘 1박으로 보정한다 — checkOut이 checkIn 이하로 무너지지 않는다", () => {
    expect(clampStayFrom(TODAY, "2026-08-10", "2026-08-12")).toEqual({
      checkIn: "2026-08-15",
      checkOut: "2026-08-16",
    });
  });
});
