// "내 예약" 보관 — 이 브라우저에서 만든 예약의 확인번호만 localStorage에 남긴다.
// (관리자 지시 2026-08-16. 시안 D7의 부분 변경 — 완료 보고서 D8로 기록)
//
// 원칙: 저장하는 건 (사용자 식별값, 확인번호) 쌍뿐이다. 상태·금액·날짜는 절대 저장하지
// 않고 항상 서버 조회로 그린다 — 서버에 없는 거짓 목록을 만들지 않기 위해서다.
// F01에 목록 API가 없으므로(백엔드에 요구하지 않는다) 이 브라우저 밖의 예약은 안 보인다.

const STORAGE_KEY = "pms.myReservations";
const MAX_PER_USER = 20;

interface StoredEntry {
  userId: string;
  code: string;
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

export function createMyReservations(storage: StorageLike) {
  function readAll(): StoredEntry[] {
    try {
      const raw = storage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(
        (e): e is StoredEntry =>
          typeof e === "object" && e !== null &&
          typeof (e as StoredEntry).userId === "string" &&
          typeof (e as StoredEntry).code === "string",
      );
    } catch {
      return []; // 깨진 저장값은 버리고 새로 시작한다
    }
  }

  return {
    /** 예약 생성 성공 직후 호출 — 최신이 앞으로, 사용자당 20건까지 */
    record(userId: string, code: string): void {
      const rest = readAll().filter((e) => !(e.userId === userId && e.code === code));
      const mine = rest.filter((e) => e.userId === userId).slice(0, MAX_PER_USER - 1);
      const others = rest.filter((e) => e.userId !== userId);
      storage.setItem(
        STORAGE_KEY,
        JSON.stringify([{ userId, code }, ...mine, ...others]),
      );
    },

    /** 이 사용자 식별값으로 만든 확인번호, 최신순 */
    list(userId: string): string[] {
      return readAll()
        .filter((e) => e.userId === userId)
        .map((e) => e.code);
    },
  };
}
