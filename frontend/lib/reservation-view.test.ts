// T5 — 상태 → 표기·행동 매핑. 시안 S3의 「상태 → 행동 매핑」 표가 진실이다.
// 서버 응답에 "가능한 행동 목록"이 없으므로 화면이 이 표 하나를 갖는다.
// 판정은 언제나 서버가 하고, 이 표가 틀리면 서버가 409로 알려준다.
import { describe, expect, it } from "vitest";
import { viewOf } from "./reservation-view";
import { computeRemainingSeconds } from "./countdown";

const base = { confirmationCode: "C-1" };

describe("viewOf — 상태 6종 + 결제 거절 변형", () => {
  it("PENDING: 결제 대기 + [결제하기, 취소]", () => {
    const v = viewOf({ ...base, status: "PENDING" });
    expect(v.badgeLabel).toBe("결제 대기");
    expect(v.actions).toEqual(["confirm", "cancel"]);
    expect(v.showCountdown).toBe(true);
  });

  it("CONFIRMED: 예약 확정 + [취소]", () => {
    const v = viewOf({ ...base, status: "CONFIRMED" });
    expect(v.badgeLabel).toBe("예약 확정");
    expect(v.actions).toEqual(["cancel"]);
  });

  it("CANCELLED(사용자 취소): 취소됨 + [다시 예약]", () => {
    const v = viewOf({ ...base, status: "CANCELLED" });
    expect(v.badgeLabel).toBe("취소됨");
    expect(v.actions).toEqual(["rebook"]);
  });

  it("CANCELLED + failureReason: 결제 거절로 구분해 말한다 — 같은 상태여도 다른 사건", () => {
    const v = viewOf({ ...base, status: "CANCELLED", failureReason: "PAYMENT_DECLINED" });
    expect(v.badgeLabel).toBe("결제 거절");
    expect(v.title).toContain("결제가 거절");
    expect(v.actions).toEqual(["rebook"]);
  });

  it("EXPIRED: 시간 초과 + [다시 예약]", () => {
    const v = viewOf({ ...base, status: "EXPIRED" });
    expect(v.badgeLabel).toBe("시간 초과");
    expect(v.actions).toEqual(["rebook"]);
  });

  it("CHECKED_IN / CHECKED_OUT: 표시만, 행동 없음 (체크인아웃 버튼 없음 — 시안 D8)", () => {
    expect(viewOf({ ...base, status: "CHECKED_IN" }).actions).toEqual([]);
    expect(viewOf({ ...base, status: "CHECKED_OUT" }).actions).toEqual([]);
  });
});

describe("computeRemainingSeconds", () => {
  const now = Date.parse("2026-09-01T14:30:00+09:00");

  it("오프셋 없는 로컬 시각은 Asia/Seoul로 해석한다 (계약 [가정])", () => {
    expect(computeRemainingSeconds("2026-09-01T14:35:00", now)).toBe(300);
  });

  it("오프셋이 있으면 그대로 쓴다", () => {
    expect(computeRemainingSeconds("2026-09-01T14:35:00+09:00", now)).toBe(300);
  });

  it("지난 시각은 0이다 — 음수 카운트다운은 없다", () => {
    expect(computeRemainingSeconds("2026-09-01T14:00:00", now)).toBe(0);
  });

  it("해석 불가 문자열은 null — 화면은 카운트다운을 숨긴다", () => {
    expect(computeRemainingSeconds("not-a-date", now)).toBeNull();
  });
});
