// 가짜 백엔드 — F01(예약)·F03(검색) 계약을 fetch 경계에서 흉내 낸다.
//
// 왜 fetch 경계인가: api.ts의 검증·오류 변환·재시도가 가짜 모드에서도 전부 실행되게
// 하기 위해서다. Api 인터페이스를 따로 구현하면 그 경로들이 가짜 모드에서 죽는다.
//
// 시드는 F01 스펙 1.9절 그대로다. 상태 전이는 같은 스펙 1.4절의 표를 따른다.
// 실제 스케줄러 대신, PENDING을 읽거나 건드리는 순간 만료 시각이 지났으면 EXPIRED로
// 옮기고 재고를 되돌린다 (한 번만).
//
// 시연용 사용자 (상단 사용자 선택에 직접 입력):
//   user-409     예약 생성이 항상 409 INSUFFICIENT_INVENTORY — 시안 S2 상태 3의 흐름 확인
//   user-503     예약 생성이 항상 503 LOCK_ACQUISITION_FAILED — 혼잡 안내 확인
//   user-decline 결제가 항상 거절 — 200 + CANCELLED + failureReason (시안 S3 상태 3)

const HOLD_MINUTES = 10; // PMS_RESERVATION_HOLD_MINUTES 기본값과 동일
const SALES_OPEN_FROM = "2026-08-01";
const SALES_OPEN_UNTIL = "2026-10-29"; // 시드 재고의 마지막 날짜

interface SeedRoomType {
  id: number;
  hotelId: number;
  name: string;
  capacity: number;
  totalQuantity: number;
  basePrice: number;
}

const ROOM_TYPES: SeedRoomType[] = [
  { id: 1, hotelId: 1, name: "스탠다드", capacity: 2, totalQuantity: 100, basePrice: 150000 },
  { id: 2, hotelId: 1, name: "디럭스", capacity: 3, totalQuantity: 50, basePrice: 250000 },
  { id: 3, hotelId: 1, name: "스위트", capacity: 4, totalQuantity: 10, basePrice: 600000 },
  { id: 4, hotelId: 2, name: "오션뷰 스탠다드", capacity: 2, totalQuantity: 80, basePrice: 180000 },
  { id: 5, hotelId: 2, name: "오션뷰 스위트", capacity: 4, totalQuantity: 20, basePrice: 450000 },
];

interface MockReservation {
  confirmationCode: string;
  userId: string;
  idempotencyKey: string;
  roomTypeId: number;
  checkIn: string;
  checkOut: string;
  nights: number;
  roomCount: number;
  guestCount: number;
  pricePerNight: number;
  totalPrice: number;
  status: "PENDING" | "CONFIRMED" | "CHECKED_IN" | "CHECKED_OUT" | "CANCELLED" | "EXPIRED";
  expiresAtMs: number;
  confirmedAtMs?: number;
  terminatedAtMs?: number;
  failureReason?: string;
  inventoryReturned: boolean;
}

function occupiedDates(checkIn: string, checkOut: string): string[] {
  // 체크아웃 당일은 점유하지 않는다 (계약)
  const dates: string[] = [];
  const d = new Date(`${checkIn}T00:00:00+09:00`);
  const end = new Date(`${checkOut}T00:00:00+09:00`);
  while (d < end) {
    dates.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }
  return dates;
}

function isoLocal(ms: number): string {
  // 서버는 Asia/Seoul 고정이다. 표시용이므로 초 단위까지만 만든다.
  return new Date(ms + 9 * 3600 * 1000).toISOString().replace("Z", "").slice(0, 19);
}

export function createMockBackend(deps: { now?: () => number; latencyMs?: number } = {}) {
  const now = deps.now ?? Date.now;
  const latencyMs = deps.latencyMs ?? 0;

  // (roomTypeId:date) → 차감량. 잔여 = totalQuantity - 차감량.
  const deducted = new Map<string, number>();
  const reservations = new Map<string, MockReservation>(); // code → 예약
  const byIdemKey = new Map<string, string>(); // `${userId}\n${key}` → code
  let seq = 1;

  const keyOf = (roomTypeId: number, date: string) => `${roomTypeId}:${date}`;
  const remainingOn = (rt: SeedRoomType, date: string) =>
    rt.totalQuantity - (deducted.get(keyOf(rt.id, date)) ?? 0);

  function applyInventory(r: Pick<MockReservation, "roomTypeId" | "checkIn" | "checkOut" | "roomCount">, delta: 1 | -1) {
    for (const date of occupiedDates(r.checkIn, r.checkOut)) {
      const k = keyOf(r.roomTypeId, date);
      deducted.set(k, (deducted.get(k) ?? 0) + delta * r.roomCount);
    }
  }

  // 만료 스케줄러 흉내: PENDING이고 시각이 지났으면 EXPIRED + 재고 복원(한 번만).
  function settleExpiry(r: MockReservation) {
    if (r.status === "PENDING" && now() >= r.expiresAtMs) {
      r.status = "EXPIRED";
      r.terminatedAtMs = now();
      if (!r.inventoryReturned) {
        applyInventory(r, -1);
        r.inventoryReturned = true;
      }
    }
  }

  function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  }

  function error(status: number, code: string, message: string): Response {
    return json(status, { code, message, traceId: `mock-${seq++}` });
  }

  function reservationBody(r: MockReservation) {
    return {
      confirmationCode: r.confirmationCode,
      status: r.status,
      roomTypeId: r.roomTypeId,
      checkIn: r.checkIn,
      checkOut: r.checkOut,
      nights: r.nights,
      roomCount: r.roomCount,
      guestCount: r.guestCount,
      pricePerNight: r.pricePerNight,
      totalPrice: r.totalPrice,
      expiresAt: isoLocal(r.expiresAtMs),
      confirmedAt: r.confirmedAtMs ? isoLocal(r.confirmedAtMs) : undefined,
      terminatedAt: r.terminatedAtMs ? isoLocal(r.terminatedAtMs) : undefined,
      failureReason: r.failureReason,
    };
  }

  function handleSearch(url: URL): Response {
    const hotelId = Number(url.searchParams.get("hotelId"));
    const checkIn = url.searchParams.get("checkIn") ?? "";
    const checkOut = url.searchParams.get("checkOut") ?? "";
    const guestCount = Number(url.searchParams.get("guestCount"));
    const roomCount = Number(url.searchParams.get("roomCount") ?? "1");

    if (![1, 2].includes(hotelId)) return error(404, "RESOURCE_NOT_FOUND", "없는 호텔");
    if (!checkIn || !checkOut || checkOut <= checkIn || guestCount < 1)
      return error(400, "INVALID_REQUEST", "검색 조건이 규칙에 어긋남");

    const base = {
      hotelId, checkIn, checkOut,
      nights: occupiedDates(checkIn, checkOut).length,
      guestCount, roomCount,
      searchedAt: isoLocal(now()) + "+09:00",
      source: "DB", // 가짜에는 캐시가 없다. 화면은 이 값을 쓰지 않는다.
      staleToleranceSeconds: 10,
    };

    // 판매 기간 밖 — 계약: 기간 밖은 200 + NOT_YET_OPEN
    if (checkOut > "2026-10-30" || checkIn < SALES_OPEN_FROM) {
      return json(200, { ...base, items: [], emptyReason: "NOT_YET_OPEN", salesOpenUntil: SALES_OPEN_UNTIL });
    }

    const inHotel = ROOM_TYPES.filter((rt) => rt.hotelId === hotelId);
    const fitting = inHotel.filter((rt) => rt.capacity * roomCount >= guestCount);
    if (fitting.length === 0) {
      return json(200, { ...base, items: [], emptyReason: "NO_FITTING_ROOM_TYPE" });
    }

    const dates = occupiedDates(checkIn, checkOut);
    const items = fitting
      .map((rt) => {
        const minRemaining = Math.min(...dates.map((d) => remainingOn(rt, d)));
        return {
          roomTypeId: rt.id,
          roomTypeName: rt.name,
          capacity: rt.capacity,
          minRemaining,
          pricePerNight: rt.basePrice,
          totalPrice: rt.basePrice * dates.length * roomCount,
        };
      })
      .filter((it) => it.minRemaining >= roomCount);

    if (items.length === 0) return json(200, { ...base, items: [], emptyReason: "SOLD_OUT" });
    return json(200, { ...base, items });
  }

  function handleCreate(headers: Headers, bodyRaw: unknown): Response {
    const userId = headers.get("X-User-Id") ?? "";
    const idemKey = headers.get("Idempotency-Key") ?? "";
    if (!userId || !idemKey) return error(400, "INVALID_REQUEST", "필수 헤더 없음");

    // 시연용 강제 실패 — 시안의 실패 상태를 언제든 재현할 수 있게 한다
    if (userId === "user-409") return error(409, "INSUFFICIENT_INVENTORY", "남은 객실 없음(시연)");
    if (userId === "user-503") return error(503, "LOCK_ACQUISITION_FAILED", "혼잡(시연)");

    const b = bodyRaw as Record<string, unknown>;
    const roomTypeId = Number(b.roomTypeId);
    const checkIn = String(b.checkIn ?? "");
    const checkOut = String(b.checkOut ?? "");
    const roomCount = Number(b.roomCount);
    const guestCount = Number(b.guestCount);

    // 멱등 재요청 — 같은 (userId, key)면 기존 예약을 200으로
    const idem = byIdemKey.get(`${userId}\n${idemKey}`);
    if (idem) {
      const existing = reservations.get(idem)!;
      settleExpiry(existing);
      return json(200, reservationBody(existing));
    }

    const rt = ROOM_TYPES.find((r) => r.id === roomTypeId);
    if (!rt) return error(404, "RESOURCE_NOT_FOUND", "없는 객실타입");
    if (!checkIn || !checkOut || checkOut <= checkIn || roomCount < 1 || guestCount < 1)
      return error(400, "INVALID_REQUEST", "입력이 규칙에 어긋남");
    if (guestCount > rt.capacity * roomCount)
      return error(400, "INVALID_REQUEST", "정원 초과");

    const dates = occupiedDates(checkIn, checkOut);
    if (checkOut > "2026-10-30" || dates.some((d) => remainingOn(rt, d) < roomCount))
      return error(409, "INSUFFICIENT_INVENTORY", "남은 객실 없음");

    const code = `${checkIn.slice(2).replaceAll("-", "")}-H${rt.hotelId}R${rt.id}-M${String(seq++).padStart(4, "0")}`;
    const r: MockReservation = {
      confirmationCode: code,
      userId,
      idempotencyKey: idemKey,
      roomTypeId,
      checkIn,
      checkOut,
      nights: dates.length,
      roomCount,
      guestCount,
      pricePerNight: rt.basePrice,
      totalPrice: rt.basePrice * dates.length * roomCount,
      status: "PENDING",
      expiresAtMs: now() + HOLD_MINUTES * 60 * 1000,
      inventoryReturned: false,
    };
    applyInventory(r, 1);
    reservations.set(code, r);
    byIdemKey.set(`${userId}\n${idemKey}`, code);
    return json(201, reservationBody(r));
  }

  function handleReservation(code: string, action: string | undefined, headers: Headers): Response {
    const userId = headers.get("X-User-Id") ?? "";
    const r = reservations.get(code);
    // 남의 예약도 404 — 존재를 숨긴다 (계약)
    if (!r || r.userId !== userId) return error(404, "RESOURCE_NOT_FOUND", "예약 없음");
    settleExpiry(r);

    if (!action) return json(200, reservationBody(r));

    if (action === "confirm") {
      if (r.status === "CONFIRMED") return json(200, reservationBody(r)); // 멱등
      if (r.status !== "PENDING")
        return error(409, "INVALID_STATE_TRANSITION", `${r.status}에서 확정 불가`);
      if (r.userId === "user-decline") {
        r.status = "CANCELLED";
        r.failureReason = "PAYMENT_DECLINED";
        r.terminatedAtMs = now();
        applyInventory(r, -1);
        r.inventoryReturned = true;
        return json(200, reservationBody(r)); // 결제 거절도 200이다
      }
      r.status = "CONFIRMED";
      r.confirmedAtMs = now();
      return json(200, reservationBody(r));
    }

    if (action === "cancel") {
      if (r.status === "CANCELLED") return json(200, reservationBody(r)); // 멱등
      if (r.status !== "PENDING" && r.status !== "CONFIRMED")
        return error(409, "INVALID_STATE_TRANSITION", `${r.status}에서 취소 불가`);
      r.status = "CANCELLED";
      r.terminatedAtMs = now();
      applyInventory(r, -1);
      r.inventoryReturned = true;
      return json(200, reservationBody(r));
    }

    return error(404, "RESOURCE_NOT_FOUND", "없는 동작");
  }

  const fetchLike: typeof fetch = async (input, init) => {
    if (latencyMs > 0) await new Promise((r) => setTimeout(r, latencyMs));
    const url = new URL(String(input), "http://mock.local");
    const path = url.pathname;

    if (path === "/api/availability") return handleSearch(url);

    const headers = new Headers(init?.headers);
    if (path === "/api/reservations" && init?.method === "POST") {
      return handleCreate(headers, init.body ? JSON.parse(String(init.body)) : {});
    }
    const m = path.match(/^\/api\/reservations\/([^/]+)(?:\/(confirm|cancel))?$/);
    if (m) return handleReservation(decodeURIComponent(m[1]), m[2], headers);

    return error(404, "RESOURCE_NOT_FOUND", `알 수 없는 경로 ${path}`);
  };

  return { fetchLike };
}
