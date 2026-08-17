// T1 — 사용자 식별값 규칙 (계약: 예약 코어 스펙 1.9 (6) — VARCHAR(64), 비어 있지 않으면 어떤 값이든)
import { describe, expect, it } from "vitest";
import { DEFAULT_USER_ID, normalizeUserId } from "./user-id";

describe("normalizeUserId", () => {
  it("정상 값은 그대로 통과한다", () => {
    expect(normalizeUserId("user-1001")).toBe("user-1001");
  });

  it("앞뒤 공백은 잘라낸다 — 공백이 섞이면 예약과 조회의 식별값이 달라진다", () => {
    expect(normalizeUserId("  user-1001  ")).toBe("user-1001");
  });

  it("빈 값·공백만인 값은 기본값으로 대체한다 — 서버가 빈 헤더를 거부한다", () => {
    expect(normalizeUserId("")).toBe(DEFAULT_USER_ID);
    expect(normalizeUserId("   ")).toBe(DEFAULT_USER_ID);
  });

  it("64자를 넘으면 기본값으로 대체한다 — DB 컬럼이 VARCHAR(64)다", () => {
    expect(normalizeUserId("a".repeat(64))).toBe("a".repeat(64));
    expect(normalizeUserId("a".repeat(65))).toBe(DEFAULT_USER_ID);
  });
});
