// 카운트다운 계산 — 라운드1 중요-4로 분리·보강 (Z 형식·formatMmSs 추가).
import { describe, expect, it } from "vitest";
import { computeRemainingSeconds, expiryFireDelayMs, formatMmSs } from "./countdown";

describe("computeRemainingSeconds", () => {
  const now = Date.parse("2026-09-01T14:30:00+09:00");

  it("오프셋 없는 로컬 시각은 Asia/Seoul로 해석한다 (계약 [가정])", () => {
    expect(computeRemainingSeconds("2026-09-01T14:35:00", now)).toBe(300);
  });

  it("오프셋이 있으면 그대로 쓴다", () => {
    expect(computeRemainingSeconds("2026-09-01T14:35:00+09:00", now)).toBe(300);
  });

  it("Z(UTC) 접미 형식도 이중 보정 없이 그대로 쓴다 — 백엔드가 형식을 바꿔도 9시간 어긋나지 않는다", () => {
    expect(computeRemainingSeconds("2026-09-01T05:35:00Z", now)).toBe(300);
  });

  it("지난 시각은 0이다 — 음수 카운트다운은 없다", () => {
    expect(computeRemainingSeconds("2026-09-01T14:00:00", now)).toBe(0);
  });

  it("해석 불가 문자열은 null — 화면은 카운트다운을 숨긴다", () => {
    expect(computeRemainingSeconds("not-a-date", now)).toBeNull();
  });
});

describe("expiryFireDelayMs — 0 도달 재조회 발화 판정 (라운드3)", () => {
  it("0 이하로 마운트된 경우(서버가 아직 PENDING)는 1초 지연 — 폴링 상한", () => {
    expect(expiryFireDelayMs(0)).toBe(1000);
    expect(expiryFireDelayMs(-5)).toBe(1000);
  });

  it("남은 시간이 있던 경우(자연 도달)는 즉시 발화", () => {
    expect(expiryFireDelayMs(300)).toBe(0);
  });

  it("해석 불가(null)는 즉시 취급 — 카운트다운 자체가 숨겨져 발화하지 않는다", () => {
    expect(expiryFireDelayMs(null)).toBe(0);
  });
});

describe("formatMmSs", () => {
  it("두 자리로 채운다", () => {
    expect(formatMmSs(587)).toBe("09:47");
    expect(formatMmSs(60)).toBe("01:00");
    expect(formatMmSs(9)).toBe("00:09");
    expect(formatMmSs(0)).toBe("00:00");
  });

  it("10분 이상도 분 단위 그대로 늘어난다", () => {
    expect(formatMmSs(600)).toBe("10:00");
  });
});
