// 직접 입력한 사용자 식별값을 저장해 셀렉트에 다시 보여준다.
// (관리자 지시 "회원가입"의 범위 내 대체 — 진짜 가입·인증은 만들지 않는다, ADR-0006)

const STORAGE_KEY = "pms.savedUserIds";
const MAX = 8;

type StorageLike = Pick<Storage, "getItem" | "setItem">;

export function createSavedUserIds(storage: StorageLike, presets: readonly string[] = []) {
  function read(): string[] {
    try {
      const parsed: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? "[]");
      return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
    } catch {
      return [];
    }
  }
  return {
    save(id: string): void {
      if (presets.includes(id)) return; // 프리셋은 이미 셀렉트에 있다
      const rest = read().filter((v) => v !== id);
      storage.setItem(STORAGE_KEY, JSON.stringify([id, ...rest].slice(0, MAX)));
    },
    list(): string[] {
      return read();
    },
  };
}
