// 위시리스트(찜) — 관리자 컨펌 기능 (2026-08-16).
// 백엔드에 저장소가 없으므로 브라우저 보관(localStorage), 사용자 식별값별로 분리한다.
// 저장하는 건 객실을 다시 찾는 데 필요한 최소 정보뿐 — 잔여·가격은 항상 서버 조회.

const STORAGE_KEY = "pms.wishlist";

export interface WishItem {
  hotelId: number;
  hotelName: string;
  roomTypeId: number;
  roomTypeName: string;
}

interface StoredEntry extends WishItem {
  userId: string;
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

export function createWishlist(storage: StorageLike) {
  function readAll(): StoredEntry[] {
    try {
      const parsed: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(
        (e): e is StoredEntry =>
          typeof e === "object" && e !== null &&
          typeof (e as StoredEntry).userId === "string" &&
          typeof (e as StoredEntry).roomTypeId === "number",
      );
    } catch {
      return [];
    }
  }

  return {
    /** 토글. 추가되면 true, 제거되면 false */
    toggle(userId: string, item: WishItem): boolean {
      const all = readAll();
      const exists = all.some((e) => e.userId === userId && e.roomTypeId === item.roomTypeId);
      const rest = all.filter((e) => !(e.userId === userId && e.roomTypeId === item.roomTypeId));
      const next = exists ? rest : [{ userId, ...item }, ...rest];
      storage.setItem(STORAGE_KEY, JSON.stringify(next));
      return !exists;
    },
    has(userId: string, roomTypeId: number): boolean {
      return readAll().some((e) => e.userId === userId && e.roomTypeId === roomTypeId);
    },
    list(userId: string): WishItem[] {
      return readAll()
        .filter((e) => e.userId === userId)
        .map(({ userId: _u, ...item }) => item);
    },
  };
}
