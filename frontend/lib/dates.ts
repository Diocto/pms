// 날짜 문자열(yyyy-MM-dd) 유틸 — 검색·상세 화면이 함께 쓴다 (두 번 반복돼서 뽑음).
// 타임존 함정을 피하려고 UTC 산술로만 계산한다. "2026-09-01" 같은 라벨은
// 어느 타임존에서 계산해도 같은 라벨이어야 한다.

export function todayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d) + days * 86_400_000;
  return new Date(t).toISOString().slice(0, 10);
}

export function nightsBetween(checkIn: string, checkOut: string): number {
  return Math.round((Date.parse(checkOut) - Date.parse(checkIn)) / 86_400_000);
}

// 재예약 날짜 보정 — 검색이 과거 checkIn을 400으로 막으므로 오늘 기준으로 클램프한다.
// checkOut이 보정된 checkIn 이하로 무너지면 최소 1박을 보장한다. (리뷰 라운드3)
export function clampStayFrom(
  today: string,
  checkIn: string,
  checkOut: string,
): { checkIn: string; checkOut: string } {
  const inDate = checkIn < today ? today : checkIn;
  const outDate = checkOut <= inDate ? addDays(inDate, 1) : checkOut;
  return { checkIn: inDate, checkOut: outDate };
}
