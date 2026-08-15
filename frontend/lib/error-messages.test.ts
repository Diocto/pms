// T2 — 에러 코드 → 화면 문구. 매핑은 이 한 곳뿐이다 (시안 「응답 → 문구 매핑」 표가 진실).
import { describe, expect, it } from "vitest";
import { messageFor } from "./error-messages";

describe("messageFor", () => {
  it("계약의 코드 7종 전부에 시안의 문구가 있다", () => {
    expect(messageFor("INVALID_REQUEST").title).toContain("확인");
    expect(messageFor("RESOURCE_NOT_FOUND").title).toContain("찾을 수 없");
    expect(messageFor("INVALID_STATE_TRANSITION").title).toContain("바뀌었");
    expect(messageFor("INSUFFICIENT_INVENTORY").title).toContain("마감");
    expect(messageFor("REQUEST_IN_PROGRESS").title).toContain("처리");
    expect(messageFor("LOCK_ACQUISITION_FAILED").title).toContain("몰리");
    expect(messageFor("INTERNAL_ERROR").title).toContain("처리하지 못했");
  });

  it("재고 부족 문구에는 돈 문장이 반드시 있다 — 실패 화면에서 가장 중요한 한 줄", () => {
    expect(messageFor("INSUFFICIENT_INVENTORY").body).toContain("결제는 진행되지 않았습니다");
  });

  it("계약에 없는 코드는 일반 오류로 떨어지고, 화면이 깨지지 않는다 (T2 완료 기준)", () => {
    const m = messageFor("SOMETHING_NEW");
    expect(m.title.length).toBeGreaterThan(0);
    expect(m.body.length).toBeGreaterThan(0);
  });

  it("traceId를 주면 문의 번호로 붙는다 — 내부 정보는 이것만 노출한다", () => {
    expect(messageFor("INTERNAL_ERROR", "tr-8c31f2").body).toContain("tr-8c31f2");
  });
});
