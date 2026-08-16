// T2 — 가짜 백엔드. fetch 경계에서 F01·F03 계약을 흉내 낸다.
// 완료 기준: 성공·실패 양쪽을 전환할 수 있다 (브리핑: "가짜를 만들 때 실패 응답도 함께").
import { beforeEach, describe, expect, it } from "vitest";
import { createApi } from "./api";
import { createMockBackend } from "./mock-backend";

const noSleep = () => Promise.resolve();

// 시각을 주입한다 — 만료 시나리오를 결정적으로 만들기 위해서다.
let nowMs: number;
let api: ReturnType<typeof createApi>;
let rawFetch: typeof fetch; // check-in/out 등 api 클라이언트에 없는 경로 호출용

beforeEach(() => {
  nowMs = Date.parse("2026-08-15T12:00:00+09:00");
  const mock = createMockBackend({ now: () => nowMs });
  rawFetch = mock.fetchLike;
  api = createApi({ fetchLike: mock.fetchLike, sleep: noSleep });
});

// 화면에 버튼이 없는 직원 액션(체크인·체크아웃)을 mock에 직접 호출한다
async function staffAction(code: string, userId: string, action: string) {
  const res = await rawFetch(`/api/reservations/${code}/${action}`, {
    method: "POST",
    headers: { "X-User-Id": userId },
  });
  return { status: res.status, body: await res.json() };
}

const search = {
  hotelId: 1, checkIn: "2026-09-01", checkOut: "2026-09-04", guestCount: 2, roomCount: 1,
};
const book = {
  roomTypeId: 3, checkIn: "2026-09-01", checkOut: "2026-09-04", roomCount: 1, guestCount: 2,
};

describe("검색", () => {
  it("시드 그대로 — 서울 그랜드 호텔 3종, 스위트 잔여 10", async () => {
    const r = await api.searchAvailability(search);
    expect(r.items.map((i) => i.roomTypeName)).toEqual(["스탠다드", "디럭스", "스위트"]);
    expect(r.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("판매 기간(2026-10-29) 밖은 NOT_YET_OPEN + salesOpenUntil", async () => {
    const r = await api.searchAvailability({ ...search, checkIn: "2026-11-01", checkOut: "2026-11-03" });
    expect(r.items).toHaveLength(0);
    expect(r.emptyReason).toBe("NOT_YET_OPEN");
    expect(r.salesOpenUntil).toBe("2026-10-29");
  });

  it("인원 5명(객실 1)은 NO_FITTING_ROOM_TYPE — 최대 정원이 4다", async () => {
    const r = await api.searchAvailability({ ...search, guestCount: 5 });
    expect(r.emptyReason).toBe("NO_FITTING_ROOM_TYPE");
  });

  it("재고가 다 팔리면 SOLD_OUT", async () => {
    for (let i = 0; i < 10; i += 1) {
      await api.createReservation(book, { userId: `user-${i}`, idempotencyKey: `k-${i}` });
    }
    const r = await api.searchAvailability({ ...search, guestCount: 4 }); // 스위트만 맞는 조건
    expect(r.items).toHaveLength(0);
    expect(r.emptyReason).toBe("SOLD_OUT");
  });
});

describe("예약 생성", () => {
  it("생성하면 PENDING + 만료 시각(10분 뒤)이 오고 재고가 줄어든다", async () => {
    const r = await api.createReservation(book, { userId: "user-1001", idempotencyKey: "k-1" });
    expect(r.status).toBe("PENDING");
    expect(r.expiresAt).toBeDefined();
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9);
  });

  it("같은 멱등성 키 재요청은 같은 예약이 오고 재고는 한 번만 줄어든다", async () => {
    const a = await api.createReservation(book, { userId: "user-1001", idempotencyKey: "k-1" });
    const b = await api.createReservation(book, { userId: "user-1001", idempotencyKey: "k-1" });
    expect(b.confirmationCode).toBe(a.confirmationCode);
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9);
  });

  it("재고를 넘겨 예약하면 409 INSUFFICIENT_INVENTORY", async () => {
    for (let i = 0; i < 10; i += 1) {
      await api.createReservation(book, { userId: `user-${i}`, idempotencyKey: `k-${i}` });
    }
    await expect(
      api.createReservation(book, { userId: "user-x", idempotencyKey: "k-x" }),
    ).rejects.toMatchObject({ code: "INSUFFICIENT_INVENTORY", status: 409 });
  });

  it("정원 초과는 400 INVALID_REQUEST", async () => {
    await expect(
      api.createReservation({ ...book, guestCount: 5 }, { userId: "u", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST", status: 400 });
  });

  it("시연용: user-409는 항상 재고 부족, user-503은 항상 혼잡", async () => {
    await expect(
      api.createReservation(book, { userId: "user-409", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "INSUFFICIENT_INVENTORY" });
    await expect(
      api.createReservation(book, { userId: "user-503", idempotencyKey: "k" }),
    ).rejects.toMatchObject({ code: "LOCK_ACQUISITION_FAILED", status: 503 });
  });
});

describe("확정·취소·만료", () => {
  it("확정하면 CONFIRMED, 다시 확정해도 멱등 성공", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    const c1 = await api.confirmReservation(r.confirmationCode, "u");
    const c2 = await api.confirmReservation(r.confirmationCode, "u");
    expect(c1.status).toBe("CONFIRMED");
    expect(c2.status).toBe("CONFIRMED");
  });

  it("시연용: user-decline은 결제 거절 — 200 + CANCELLED + failureReason, 재고 복원", async () => {
    const r = await api.createReservation(book, { userId: "user-decline", idempotencyKey: "k" });
    const c = await api.confirmReservation(r.confirmationCode, "user-decline");
    expect(c.status).toBe("CANCELLED");
    expect(c.failureReason).toBe("PAYMENT_DECLINED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("취소하면 재고가 돌아오고, 재취소는 멱등 성공", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    await api.cancelReservation(r.confirmationCode, "u");
    const again = await api.cancelReservation(r.confirmationCode, "u");
    expect(again.status).toBe("CANCELLED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("10분이 지나면 조회 시 EXPIRED가 되고 재고가 돌아온다 (스케줄러 흉내)", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    nowMs += 11 * 60 * 1000;
    const g = await api.getReservation(r.confirmationCode, "u");
    expect(g.status).toBe("EXPIRED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("만료 뒤 확정 시도는 409 INVALID_STATE_TRANSITION", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    nowMs += 11 * 60 * 1000;
    await expect(api.confirmReservation(r.confirmationCode, "u")).rejects.toMatchObject({
      code: "INVALID_STATE_TRANSITION",
      status: 409,
    });
  });

  it("남의 예약은 403이 아니라 404다 — 존재를 숨긴다", async () => {
    const r = await api.createReservation(book, { userId: "u-mine", idempotencyKey: "k" });
    await expect(api.getReservation(r.confirmationCode, "u-other")).rejects.toMatchObject({
      code: "RESOURCE_NOT_FOUND",
      status: 404,
    });
  });
});

// PR #38 — 호텔 목록·예약 목록 API
describe("호텔 목록 · 예약 목록 (PR #38)", () => {
  it("호텔 100곳, 확장 객실타입 id는 ×1000 규칙", async () => {
    const hotels = await api.fetchHotels();
    expect(hotels).toHaveLength(100);
    expect(hotels[0].name).toBe("서울 그랜드 호텔");
    const h50 = hotels.find((h) => h.hotelId === 50)!;
    // 리비전 054 — 이름·주소가 id 대역별 지역에서 유도된다 (실 백엔드와 같은 규칙)
    expect(h50.name).toBe("제주 호텔 050");
    expect(h50.address).toBe("제주특별자치도 제주시 중앙로 50");
    expect(h50.roomTypes.map((r) => r.roomTypeId)).toEqual([50001, 50002, 50003]);
    // 대역 경계 — 여기가 어긋나면 지역이 통째로 밀린다
    expect(hotels.find((h) => h.hotelId === 36)!.name).toBe("부산 호텔 036");
    expect(hotels.find((h) => h.hotelId === 37)!.name).toBe("제주 호텔 037");
    expect(hotels.find((h) => h.hotelId === 100)!.name).toBe("대구 호텔 100");
  });

  it("목록은 사용자 자신의 예약만 최신순으로, 없으면 빈 배열", async () => {
    expect(await api.listReservations("user-empty")).toEqual([]);
    await api.createReservation(book, { userId: "u-list", idempotencyKey: "L-1" });
    const second = await api.createReservation(
      { ...book, checkIn: "2026-09-10", checkOut: "2026-09-11" },
      { userId: "u-list", idempotencyKey: "L-2" },
    );
    await api.createReservation(book, { userId: "u-other", idempotencyKey: "L-3" });
    const rows = await api.listReservations("u-list");
    expect(rows).toHaveLength(2);
    expect(rows[0].confirmationCode).toBe(second.confirmationCode); // 최신 먼저
  });

  it("status 필터가 서버에서 걸린다 — 결제 완료(CONFIRMED)만", async () => {
    const a = await api.createReservation(book, { userId: "u-f", idempotencyKey: "F-1" });
    await api.confirmReservation(a.confirmationCode, "u-f");
    await api.createReservation(
      { ...book, checkIn: "2026-09-10", checkOut: "2026-09-11" },
      { userId: "u-f", idempotencyKey: "F-2" },
    );
    const confirmed = await api.listReservations("u-f", "CONFIRMED");
    expect(confirmed).toHaveLength(1);
    expect(confirmed[0].status).toBe("CONFIRMED");
  });
});

// 투숙 리뷰 — 더미 API (관리자 컨펌)
describe("투숙 리뷰 (더미 API)", () => {
  it("시드 리뷰가 객실타입별로 조회된다", async () => {
    const rv = await api.listReviews(3);
    expect(rv.length).toBeGreaterThanOrEqual(2);
    expect(rv.every((r) => r.roomTypeId === 3)).toBe(true);
  });

  it("작성하면 목록 맨 앞에 실린다", async () => {
    const before = (await api.listReviews(1)).length;
    await api.createReview({ roomTypeId: 1, rating: 4, comment: "좋았어요" }, "u-review");
    const after = await api.listReviews(1);
    expect(after).toHaveLength(before + 1);
    expect(after[0].comment).toBe("좋았어요");
    expect(after[0].userId).toBe("u-review");
  });

  it("별점 범위 밖·빈 코멘트는 400", async () => {
    await expect(
      api.createReview({ roomTypeId: 1, rating: 6, comment: "x" }, "u"),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
    await expect(
      api.createReview({ roomTypeId: 1, rating: 5, comment: "  " }, "u"),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  });
});

// 라운드1 중요-7 — 예약 생성의 날짜 창
describe("날짜 창 (F01 D21·시드 범위)", () => {
  it("이미 끝난 숙박(checkOut <= today)은 400 — 실 백엔드와 같은 거절", async () => {
    await expect(
      api.createReservation(
        { ...book, checkIn: "2026-07-01", checkOut: "2026-07-05" },
        { userId: "u", idempotencyKey: "k" },
      ),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST", status: 400 });
  });

  it("진행 중 투숙(checkIn 과거, checkOut 미래)은 허용된다 — D21", async () => {
    const r = await api.createReservation(
      { ...book, checkIn: "2026-08-14", checkOut: "2026-08-17" },
      { userId: "u", idempotencyKey: "k" },
    );
    expect(r.status).toBe("PENDING");
  });

  it("판매 개시일(2026-08-01) 이전 시작은 재고 행이 없어 409", async () => {
    await expect(
      api.createReservation(
        { ...book, checkIn: "2026-07-30", checkOut: "2026-08-20" },
        { userId: "u", idempotencyKey: "k" },
      ),
    ).rejects.toMatchObject({ code: "INSUFFICIENT_INVENTORY", status: 409 });
  });

  it("검색의 과거 checkIn은 400이다 (F03: 검색은 과거를 막는다)", async () => {
    await expect(
      api.searchAvailability({ ...search, checkIn: "2026-08-10", checkOut: "2026-08-12" }),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST", status: 400 });
  });
});

// 라운드2 중요 — HTTP로 도달 가능한 전 칸(상태 6 × 이벤트 4 = 24)의 테이블 주도 전수.
// 진실은 F01 스펙 1.4 전수 표다. 표를 바꾸지 않고 분기 순서만 바꿔도 여기서 잡힌다.
describe("전이 표 — 24칸 전수", () => {
  const stay = { ...book, checkIn: "2026-08-15", checkOut: "2026-08-17" }; // 오늘 체크인 가능

  type State = "PENDING" | "CONFIRMED" | "CHECKED_IN" | "CHECKED_OUT" | "CANCELLED" | "EXPIRED";
  type Event = "confirm" | "cancel" | "check-in" | "check-out";

  async function prepare(state: State): Promise<string> {
    const r = await api.createReservation(stay, { userId: "u", idempotencyKey: `prep-${state}` });
    const code = r.confirmationCode;
    if (state === "CONFIRMED" || state === "CHECKED_IN" || state === "CHECKED_OUT")
      await api.confirmReservation(code, "u");
    if (state === "CHECKED_IN" || state === "CHECKED_OUT") await staffAction(code, "u", "check-in");
    if (state === "CHECKED_OUT") await staffAction(code, "u", "check-out");
    if (state === "CANCELLED") await api.cancelReservation(code, "u");
    if (state === "EXPIRED") nowMs += 11 * 60 * 1000; // 다음 접근에서 스케줄러 흉내가 옮긴다
    return code;
  }

  // 기대값: 숫자면 그 HTTP 상태로 거부(409), 문자열이면 200 + 그 상태(전이 또는 멱등)
  const TABLE: Record<State, Record<Event, number | State>> = {
    PENDING: { confirm: "CONFIRMED", cancel: "CANCELLED", "check-in": 409, "check-out": 409 },
    CONFIRMED: { confirm: "CONFIRMED", cancel: "CANCELLED", "check-in": "CHECKED_IN", "check-out": 409 },
    CHECKED_IN: { confirm: 409, cancel: 409, "check-in": "CHECKED_IN", "check-out": "CHECKED_OUT" },
    CHECKED_OUT: { confirm: 409, cancel: 409, "check-in": 409, "check-out": "CHECKED_OUT" },
    CANCELLED: { confirm: 409, cancel: "CANCELLED", "check-in": 409, "check-out": 409 },
    EXPIRED: { confirm: 409, cancel: 409, "check-in": 409, "check-out": 409 },
  };

  // Object.entries는 키를 string으로 넓혀 as가 필요해진다 — 타입된 키 배열로 순회 (라운드3)
  const STATES: readonly State[] = ["PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "EXPIRED"];
  const EVENTS: readonly Event[] = ["confirm", "cancel", "check-in", "check-out"];
  for (const state of STATES) {
    for (const event of EVENTS) {
      const expected = TABLE[state][event];
      it(`${state} + ${event} → ${typeof expected === "number" ? `거부 ${expected}` : expected}`, async () => {
        const code = await prepare(state);
        const res = await staffAction(code, "u", event);
        if (typeof expected === "number") {
          expect(res.status).toBe(expected);
          expect(res.body.code).toBe("INVALID_STATE_TRANSITION");
        } else {
          expect(res.status).toBe(200);
          expect(res.body.status).toBe(expected);
        }
      });
    }
  }

  it("CHECKED_IN + cancel 거부 시 재고도 불변이다 — 이미 팔린 밤은 되돌리지 않는다", async () => {
    const code = await prepare("CHECKED_IN");
    const before = await api.searchAvailability({
      hotelId: 1, checkIn: "2026-08-15", checkOut: "2026-08-17", guestCount: 4, roomCount: 1,
    });
    expect(before.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9);
    await staffAction(code, "u", "cancel"); // 409
    const after = await api.searchAvailability({
      hotelId: 1, checkIn: "2026-08-15", checkOut: "2026-08-17", guestCount: 4, roomCount: 1,
    });
    expect(after.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9);
  });
});

// 라운드1 중요-8 — 스펙이 강조한 칸의 부수 효과(재고)까지 검증
describe("전이 표 — 스펙이 강조한 칸", () => {
  it("EXPIRED + CANCEL = 409 — '이미 취소됨'으로 조용히 성공시키지 않는다", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    nowMs += 11 * 60 * 1000;
    await expect(api.cancelReservation(r.confirmationCode, "u")).rejects.toMatchObject({
      code: "INVALID_STATE_TRANSITION",
      status: 409,
    });
  });

  it("CANCELLED + CONFIRM = 409", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    await api.cancelReservation(r.confirmationCode, "u");
    await expect(api.confirmReservation(r.confirmationCode, "u")).rejects.toMatchObject({
      code: "INVALID_STATE_TRANSITION",
    });
  });

  it("CONFIRMED + CANCEL = 취소되고 재고가 복원된다", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    await api.confirmReservation(r.confirmationCode, "u");
    const c = await api.cancelReservation(r.confirmationCode, "u");
    expect(c.status).toBe("CANCELLED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });

  it("만료 후 반복 조회·취소 시도에도 복원은 정확히 한 번 — 잔여가 총량을 넘지 않는다", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    nowMs += 11 * 60 * 1000;
    await api.getReservation(r.confirmationCode, "u");
    await api.getReservation(r.confirmationCode, "u");
    await api.cancelReservation(r.confirmationCode, "u").catch(() => {});
    const s = await api.searchAvailability({ ...search, guestCount: 4 });
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10); // 10 초과 금지
  });

  it("CONFIRMED는 만료 시각이 지나도 만료되지 않는다 — 결제된 예약이 조회 순간 사라지면 안 된다", async () => {
    // F01 1.4 "읽는 법 주의": CONFIRMED + EXPIRE = 거부. settleExpiry 가드의 회귀 감지용
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" });
    await api.confirmReservation(r.confirmationCode, "u");
    nowMs += 11 * 60 * 1000;
    const g = await api.getReservation(r.confirmationCode, "u");
    expect(g.status).toBe("CONFIRMED");
    const s = await api.searchAvailability(search);
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(9); // 재고 복원 없음
  });

  it("만료된 PENDING은 예약을 따로 읽지 않아도 검색에서 복원돼 보인다 (스윕)", async () => {
    for (let i = 0; i < 10; i += 1) {
      await api.createReservation(book, { userId: `user-${i}`, idempotencyKey: `k-${i}` });
    }
    nowMs += 11 * 60 * 1000;
    const s = await api.searchAvailability({ ...search, guestCount: 4 });
    expect(s.items.find((i) => i.roomTypeId === 3)?.minRemaining).toBe(10);
  });
});

// 라운드1 제안 — mock의 체크인·체크아웃 경로 (화면 버튼은 D8대로 없음)
describe("체크인·체크아웃 (직원 액션, mock 경로)", () => {
  const stay = { ...book, checkIn: "2026-08-15", checkOut: "2026-08-17" }; // 오늘 체크인

  it("CONFIRMED에서 체크인 → CHECKED_IN, 재체크인은 멱등", async () => {
    const r = await api.createReservation(stay, { userId: "u", idempotencyKey: "k" });
    await api.confirmReservation(r.confirmationCode, "u");
    expect((await staffAction(r.confirmationCode, "u", "check-in")).body.status).toBe("CHECKED_IN");
    expect((await staffAction(r.confirmationCode, "u", "check-in")).status).toBe(200);
  });

  it("PENDING 체크인은 409 — 전이 표에 없는 조합", async () => {
    const r = await api.createReservation(stay, { userId: "u", idempotencyKey: "k" });
    expect((await staffAction(r.confirmationCode, "u", "check-in")).status).toBe(409);
  });

  it("체크인 가능 기간 밖(미래 숙박)은 CONFIRMED여도 409", async () => {
    const r = await api.createReservation(book, { userId: "u", idempotencyKey: "k" }); // 9월 숙박
    await api.confirmReservation(r.confirmationCode, "u");
    expect((await staffAction(r.confirmationCode, "u", "check-in")).status).toBe(409);
  });

  it("CHECKED_IN → 체크아웃 → CHECKED_OUT (종료 상태). 취소는 409", async () => {
    const r = await api.createReservation(stay, { userId: "u", idempotencyKey: "k" });
    await api.confirmReservation(r.confirmationCode, "u");
    await staffAction(r.confirmationCode, "u", "check-in");
    expect((await staffAction(r.confirmationCode, "u", "check-out")).body.status).toBe("CHECKED_OUT");
    await expect(api.cancelReservation(r.confirmationCode, "u")).rejects.toMatchObject({
      code: "INVALID_STATE_TRANSITION",
    });
  });
});
