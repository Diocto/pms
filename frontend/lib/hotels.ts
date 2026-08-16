// 호텔·객실타입 유도 규칙.
//
// 호텔 목록의 진실은 GET /api/hotels다 (호텔 100곳 — 상수 2곳 시대는 끝났다).
// 여기 남는 것은 "예약 응답의 roomTypeId → 소속 hotelId" 유도 규칙뿐이다:
// 시드 계약(PR #38): 확장 객실타입 id = 호텔id × 1000 + n (n=1..3),
// 기존 1~5는 1~3→서울 그랜드(1), 4~5→부산 오션뷰(2)로 동결.

const LEGACY: Record<number, number> = { 1: 1, 2: 1, 3: 1, 4: 2, 5: 2 };

export function hotelIdOfRoomType(roomTypeId: number | undefined): number | undefined {
  if (roomTypeId === undefined) return undefined;
  if (roomTypeId >= 1000) return Math.floor(roomTypeId / 1000);
  return LEGACY[roomTypeId];
}
