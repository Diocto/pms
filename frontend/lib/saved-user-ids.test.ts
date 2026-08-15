// 사용자 식별값 선택 확장 (관리자 지시 "회원가입"의 범위 내 대체 — ADR-0006:
// 진짜 가입은 만들지 않는다). 직접 입력한 식별값을 저장해 셀렉트에 다시 보여준다.
import { describe, expect, it } from "vitest";
import { createSavedUserIds } from "./saved-user-ids";

function memoryStorage(): Pick<Storage, "getItem" | "setItem"> {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
}

describe("createSavedUserIds", () => {
  it("저장한 식별값을 최신순으로 돌려주고, 중복은 한 번만", () => {
    const s = createSavedUserIds(memoryStorage());
    s.save("guest-kim");
    s.save("guest-lee");
    s.save("guest-kim");
    expect(s.list()).toEqual(["guest-kim", "guest-lee"]);
  });

  it("기본 프리셋과 겹치는 값은 저장하지 않는다", () => {
    const s = createSavedUserIds(memoryStorage(), ["user-1001"]);
    s.save("user-1001");
    expect(s.list()).toEqual([]);
  });

  it("최대 8건 — 오래된 것부터 밀려나고, 깨진 저장값은 빈 목록으로 시작한다", () => {
    const storage = memoryStorage();
    storage.setItem("pms.savedUserIds", "broken");
    const s = createSavedUserIds(storage);
    for (let i = 1; i <= 10; i += 1) s.save(`g-${i}`);
    expect(s.list()).toHaveLength(8);
    expect(s.list()[0]).toBe("g-10");
  });
});
