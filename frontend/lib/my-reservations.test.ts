// "내 예약" — 이 브라우저에서 만든 예약의 확인번호 보관 (관리자 지시 2026-08-16).
// 저장하는 건 확인번호뿐이고 상태는 항상 서버 조회로 그린다 — 서버에 없는 거짓 목록을
// 만들지 않는다 (시안 D7의 우려 지점). storage는 주입받아 테스트한다.
import { describe, expect, it } from "vitest";
import { createMyReservations } from "./my-reservations";

function memoryStorage(): Pick<Storage, "getItem" | "setItem"> {
  const m = new Map<string, string>();
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, v),
  };
}

describe("createMyReservations", () => {
  it("기록한 확인번호를 같은 사용자 기준 최신순으로 돌려준다", () => {
    const mine = createMyReservations(memoryStorage());
    mine.record("user-1", "CODE-A");
    mine.record("user-1", "CODE-B");
    expect(mine.list("user-1")).toEqual(["CODE-B", "CODE-A"]);
  });

  it("사용자 식별값이 다르면 목록도 다르다 — 남의 코드가 섞이지 않는다", () => {
    const mine = createMyReservations(memoryStorage());
    mine.record("user-1", "CODE-A");
    expect(mine.list("user-2")).toEqual([]);
  });

  it("같은 코드를 두 번 기록해도 한 번만 남는다 (멱등 재요청 대비)", () => {
    const mine = createMyReservations(memoryStorage());
    mine.record("user-1", "CODE-A");
    mine.record("user-1", "CODE-A");
    expect(mine.list("user-1")).toEqual(["CODE-A"]);
  });

  it("보관은 최근 20건까지 — 오래된 것부터 밀려난다", () => {
    const mine = createMyReservations(memoryStorage());
    for (let i = 1; i <= 25; i += 1) mine.record("user-1", `C-${i}`);
    const list = mine.list("user-1");
    expect(list).toHaveLength(20);
    expect(list[0]).toBe("C-25");
    expect(list).not.toContain("C-5");
  });

  it("저장소가 깨진 값을 갖고 있어도 빈 목록으로 시작한다", () => {
    const s = memoryStorage();
    s.setItem("pms.myReservations", "not-json");
    const mine = createMyReservations(s);
    expect(mine.list("user-1")).toEqual([]);
    mine.record("user-1", "CODE-A"); // 기록도 계속 동작한다
    expect(mine.list("user-1")).toEqual(["CODE-A"]);
  });
});
