// 위시리스트(찜) — 관리자 컨펌 기능 (2026-08-16). 브라우저 보관, 사용자 식별값별.
import { describe, expect, it } from "vitest";
import { createWishlist } from "./wishlist";

function memoryStorage(): Pick<Storage, "getItem" | "setItem"> {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
}

const item = { hotelId: 1, hotelName: "서울 그랜드 호텔", roomTypeId: 3, roomTypeName: "스위트" };

describe("createWishlist", () => {
  it("토글 — 없으면 추가, 있으면 제거", () => {
    const w = createWishlist(memoryStorage());
    expect(w.toggle("u1", item)).toBe(true);
    expect(w.has("u1", 3)).toBe(true);
    expect(w.toggle("u1", item)).toBe(false);
    expect(w.has("u1", 3)).toBe(false);
  });

  it("사용자 식별값별로 분리된다", () => {
    const w = createWishlist(memoryStorage());
    w.toggle("u1", item);
    expect(w.has("u2", 3)).toBe(false);
    expect(w.list("u2")).toEqual([]);
  });

  it("최신 찜이 앞으로, 깨진 저장값은 빈 목록", () => {
    const s = memoryStorage();
    s.setItem("pms.wishlist", "broken");
    const w = createWishlist(s);
    w.toggle("u1", item);
    w.toggle("u1", { ...item, roomTypeId: 50003, roomTypeName: "스위트", hotelId: 50, hotelName: "호텔 050" });
    expect(w.list("u1")[0].roomTypeId).toBe(50003);
  });
});
