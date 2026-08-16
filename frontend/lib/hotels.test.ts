// roomTypeId → hotelId 유도 규칙 (시드 계약 PR #38: 확장 id = 호텔id×1000+n, 1~5는 동결)
import { describe, expect, it } from "vitest";
import { hotelIdOfRoomType } from "./hotels";

describe("hotelIdOfRoomType", () => {
  it("동결된 1~5는 기존 매핑", () => {
    expect(hotelIdOfRoomType(1)).toBe(1);
    expect(hotelIdOfRoomType(3)).toBe(1);
    expect(hotelIdOfRoomType(4)).toBe(2);
    expect(hotelIdOfRoomType(5)).toBe(2);
  });

  it("확장 id는 ×1000 규칙으로 유도", () => {
    expect(hotelIdOfRoomType(50001)).toBe(50);
    expect(hotelIdOfRoomType(100003)).toBe(100);
    expect(hotelIdOfRoomType(3002)).toBe(3);
  });

  it("모르는 값은 undefined — rebook은 hotelId 없이 검색 기본값에 맡긴다", () => {
    expect(hotelIdOfRoomType(undefined)).toBeUndefined();
    expect(hotelIdOfRoomType(999)).toBeUndefined();
  });
});
