// T4 — 409의 4단계 흐름 (시안 S2 상태 3, 브리핑 권장 흐름 그대로).
// ① 409 수신 → ② fresh=true 재검색 → ③ 남아 있으면 같은 키로 자동 재시도 → ④ 최대 2회 실패 시 마감.
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { attemptBooking, type BookingPhase } from "./booking-flow";

const CREATED = { confirmationCode: "C-1", status: "PENDING" as const };
const inventory409 = new ApiError(409, "INSUFFICIENT_INVENTORY");

describe("attemptBooking", () => {
  it("첫 시도에 성공하면 재검색 없이 끝난다", async () => {
    const create = vi.fn(async () => CREATED);
    const checkFresh = vi.fn(async () => true);
    const r = await attemptBooking({ create, checkFresh, onPhase: () => {} });
    expect(r).toEqual({ kind: "created", reservation: CREATED });
    expect(checkFresh).not.toHaveBeenCalled();
  });

  it("409 → 최신 재고 있음 → 자동 재시도로 성공한다. 사용자는 다시 누르지 않는다", async () => {
    const create = vi
      .fn()
      .mockRejectedValueOnce(inventory409)
      .mockResolvedValueOnce(CREATED);
    const checkFresh = vi.fn(async () => true);
    const r = await attemptBooking({ create, checkFresh, onPhase: () => {} });
    expect(r.kind).toBe("created");
    expect(create).toHaveBeenCalledTimes(2);
    expect(checkFresh).toHaveBeenCalledTimes(1);
  });

  it("409 → 최신 재고 없음 → 재시도하지 않고 마감으로 끝난다", async () => {
    const create = vi.fn().mockRejectedValue(inventory409);
    const checkFresh = vi.fn(async () => false);
    const r = await attemptBooking({ create, checkFresh, onPhase: () => {} });
    expect(r.kind).toBe("sold-out");
    expect(create).toHaveBeenCalledTimes(1); // 없는 재고에 다시 부딪히지 않는다
  });

  it("자동 재시도는 최대 2회 — 세 번째 409에서 마감으로 끝난다", async () => {
    const create = vi.fn().mockRejectedValue(inventory409);
    const checkFresh = vi.fn(async () => true);
    const r = await attemptBooking({ create, checkFresh, onPhase: () => {} });
    expect(r.kind).toBe("sold-out");
    expect(create).toHaveBeenCalledTimes(3); // 최초 1 + 재시도 2
  });

  it("409가 아닌 오류(503 등)는 흐름을 태우지 않고 그대로 던진다", async () => {
    const create = vi.fn().mockRejectedValue(new ApiError(503, "LOCK_ACQUISITION_FAILED"));
    const checkFresh = vi.fn(async () => true);
    await expect(
      attemptBooking({ create, checkFresh, onPhase: () => {} }),
    ).rejects.toMatchObject({ code: "LOCK_ACQUISITION_FAILED" });
    expect(checkFresh).not.toHaveBeenCalled();
  });

  it("진행 단계를 순서대로 알린다 — 화면이 이 콜백으로 진행 카드를 그린다", async () => {
    const phases: BookingPhase[] = [];
    const create = vi
      .fn()
      .mockRejectedValueOnce(inventory409)
      .mockResolvedValueOnce(CREATED);
    await attemptBooking({
      create,
      checkFresh: async () => true,
      onPhase: (p) => phases.push(p),
    });
    expect(phases).toEqual([
      { kind: "submitting" },
      { kind: "sold-just-now", attempt: 1 },
      { kind: "checking-fresh", attempt: 1 },
      { kind: "retrying", attempt: 1 },
    ]);
  });
});
