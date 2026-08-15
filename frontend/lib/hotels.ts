// 호텔 목록 API는 없다 — 시드 2곳을 상수로 갖는다 (시안 D7, F01 스펙 1.9 (2)).
export const HOTELS = [
  { id: 1, name: "서울 그랜드 호텔" },
  { id: 2, name: "부산 오션뷰 호텔" },
] as const;

// 예약 응답에는 hotelId가 없다 — roomTypeId(시드 1~5)로 소속 호텔을 유도한다.
// 시드가 진실(F01 스펙 1.9 (3)): 1~3 = 서울 그랜드, 4~5 = 부산 오션뷰.
const ROOM_TYPE_HOTEL: Record<number, number> = { 1: 1, 2: 1, 3: 1, 4: 2, 5: 2 };

export function hotelIdOfRoomType(roomTypeId: number | undefined): number | undefined {
  return roomTypeId === undefined ? undefined : ROOM_TYPE_HOTEL[roomTypeId];
}
