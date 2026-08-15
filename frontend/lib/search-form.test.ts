// T3 — 검색 폼 검증. 클라이언트 검증은 UX다. 판정은 서버가 한다 —
// 여기 규칙은 F03 계약의 400 조건을 미리 알려주는 것뿐이다.
import { describe, expect, it } from "vitest";
import { validateSearchForm } from "./search-form";

const TODAY = "2026-08-15";
const ok = { checkIn: "2026-09-01", checkOut: "2026-09-04", guestCount: 2, roomCount: 1 };

describe("validateSearchForm", () => {
  it("정상 입력은 오류가 없다", () => {
    expect(validateSearchForm(ok, TODAY)).toEqual({});
  });

  it("체크아웃은 체크인보다 뒤여야 한다", () => {
    const e = validateSearchForm({ ...ok, checkOut: "2026-09-01" }, TODAY);
    expect(e.checkOut).toContain("뒤");
  });

  it("과거 체크인은 막는다 — 검색 계약은 오늘 이상만 받는다", () => {
    const e = validateSearchForm({ ...ok, checkIn: "2026-08-10", checkOut: "2026-08-12" }, TODAY);
    expect(e.checkIn).toBeDefined();
  });

  it("30박을 넘으면 막는다", () => {
    const e = validateSearchForm({ ...ok, checkOut: "2026-10-02" }, TODAY); // 31박
    expect(e.checkOut).toContain("30");
  });

  it("인원은 1~20, 객실 수는 1~10", () => {
    expect(validateSearchForm({ ...ok, guestCount: 0 }, TODAY).guestCount).toBeDefined();
    expect(validateSearchForm({ ...ok, guestCount: 21 }, TODAY).guestCount).toBeDefined();
    expect(validateSearchForm({ ...ok, roomCount: 0 }, TODAY).roomCount).toBeDefined();
    expect(validateSearchForm({ ...ok, roomCount: 11 }, TODAY).roomCount).toBeDefined();
  });
});
