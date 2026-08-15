// 호텔 목록 카드의 요약 — 호텔별 검색 응답 1건을 카드 한 장으로 접는다.
// (검색 흐름 개선: 검색 → 호텔 목록 → 호텔 선택 → 객실 선택. 관리자 지시 2026-08-16)

import type { AvailabilityResponse, EmptyReason } from "./contracts";

export type HotelSummary =
  | { kind: "available"; roomTypeCount: number; minTotalPrice: number }
  | { kind: EmptyReason };

export function summarizeHotel(res: AvailabilityResponse): HotelSummary {
  if (res.items.length > 0) {
    return {
      kind: "available",
      roomTypeCount: res.items.length,
      minTotalPrice: Math.min(...res.items.map((i) => i.totalPrice)),
    };
  }
  // emptyReason 부재 시 매진으로 — 잘못 파는 것보다 안 파는 쪽이 안전하다 (계약과 같은 방향)
  return { kind: res.emptyReason ?? "SOLD_OUT" };
}
