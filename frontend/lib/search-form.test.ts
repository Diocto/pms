// T3 — 검색 폼 검증. 클라이언트 검증은 UX다. 판정은 서버가 한다 —
// 여기 규칙은 검색 계약의 400 조건(과거 날짜·뒤집힌 기간·인원 범위)을 미리 알려주는 것뿐이다.
// 박수 상한은 없다 — 서버가 400이 아니라 NOT_YET_OPEN으로 답하기 때문 (D29).
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

  it("긴 기간도 막지 않는다 — 박수 상한 없음 (D29)", () => {
    // 상한을 되살리면 여기가 빨강이 된다. 판매 기간을 넘는 요청은 서버가 400이 아니라
    // 200 + NOT_YET_OPEN + salesOpenUntil로 답하고, 화면이 그걸 안내로 그린다.
    expect(validateSearchForm({ ...ok, checkOut: "2026-10-02" }, TODAY).checkOut).toBeUndefined(); // 31박
    expect(validateSearchForm({ ...ok, checkOut: "2027-10-11" }, TODAY).checkOut).toBeUndefined(); // 405박
  });

  it("인원은 1~20, 객실 수는 1~10", () => {
    expect(validateSearchForm({ ...ok, guestCount: 0 }, TODAY).guestCount).toBeDefined();
    expect(validateSearchForm({ ...ok, guestCount: 21 }, TODAY).guestCount).toBeDefined();
    expect(validateSearchForm({ ...ok, roomCount: 0 }, TODAY).roomCount).toBeDefined();
    expect(validateSearchForm({ ...ok, roomCount: 11 }, TODAY).roomCount).toBeDefined();
  });
});
