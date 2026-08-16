"use client";

// S1 객실 검색 — 호텔 100곳 대응 (관리자 지시·PR #38 반영).
// 1단: 호텔 목록은 GET /api/hotels가 진실 (이름 필터, 잔여 없음 — 계약).
// 2단: 호텔을 고르면 그 호텔만 GET /api/availability로 잔여·요금을 조회한다.
// 조건·선택 호텔은 전부 URL 쿼리가 진실이다(시안 D4).

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/backend";
import { addDays, todayLocal } from "@/lib/dates";
import { messageForError } from "@/lib/error-messages";
import { validateSearchForm, type SearchFormErrors } from "@/lib/search-form";
import { createWishlist, type WishItem } from "@/lib/wishlist";
import { useUserId } from "@/components/user-context";
import type { AvailabilityResponse, HotelInfo } from "@/lib/contracts";

function won(n: number): string {
  return n.toLocaleString("ko-KR");
}

type HotelsState =
  | { kind: "loading" }
  | { kind: "loaded"; hotels: HotelInfo[] }
  | { kind: "error"; body: string };

type AvailState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "loaded"; data: AvailabilityResponse }
  | { kind: "error"; body: string };

function SearchScreen() {
  const router = useRouter();
  const params = useSearchParams();

  const [checkIn, setCheckIn] = useState(params.get("checkIn") ?? "");
  const [checkOut, setCheckOut] = useState(params.get("checkOut") ?? "");
  const [guestCount, setGuestCount] = useState(Number(params.get("guestCount") ?? 2));
  const [roomCount, setRoomCount] = useState(Number(params.get("roomCount") ?? 1));
  const [errors, setErrors] = useState<SearchFormErrors>({});
  const [hotels, setHotels] = useState<HotelsState>({ kind: "loading" });
  const [avail, setAvail] = useState<AvailState>({ kind: "idle" });
  const [nameFilter, setNameFilter] = useState("");
  const checkInRef = useRef<HTMLInputElement>(null);

  // 위시리스트(찜) — 관리자 컨펌 기능. localStorage는 마운트 후에만 읽는다(하이드레이션)
  const { userId } = useUserId();
  const [wished, setWished] = useState<WishItem[]>([]);
  const [wishSeq, setWishSeq] = useState(0);
  useEffect(() => {
    setWished(createWishlist(window.localStorage).list(userId));
  }, [userId, wishSeq]);
  const toggleWish = useCallback(
    (item: WishItem) => {
      createWishlist(window.localStorage).toggle(userId, item);
      setWishSeq((v) => v + 1);
    },
    [userId],
  );

  const urlQuery = params.toString();
  const selectedHotelId = params.get("hotelId") ? Number(params.get("hotelId")) : null;
  const hasDates = Boolean(params.get("checkIn") && params.get("checkOut"));

  // 호텔 목록 — 시드 고정이라 1회만 불러온다
  useEffect(() => {
    let cancelled = false;
    api
      .fetchHotels()
      .then((list) => {
        if (!cancelled) setHotels({ kind: "loaded", hotels: list });
      })
      .catch((e: unknown) => {
        if (!cancelled) setHotels({ kind: "error", body: messageForError(e).body });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 호텔이 선택되고 날짜가 있으면 그 호텔의 가용 조회
  useEffect(() => {
    const q = new URLSearchParams(urlQuery);
    const cIn = q.get("checkIn");
    const cOut = q.get("checkOut");
    const hid = q.get("hotelId");
    if (!cIn || !cOut || !hid) {
      setAvail({ kind: "idle" });
      return;
    }
    let cancelled = false;
    setAvail({ kind: "loading" });
    api
      .searchAvailability({
        hotelId: Number(hid),
        checkIn: cIn,
        checkOut: cOut,
        guestCount: Number(q.get("guestCount") ?? 2),
        roomCount: Number(q.get("roomCount") ?? 1),
      })
      .then((data) => {
        if (!cancelled) setAvail({ kind: "loaded", data });
      })
      .catch((e: unknown) => {
        if (!cancelled) setAvail({ kind: "error", body: messageForError(e).body });
      });
    return () => {
      cancelled = true;
    };
  }, [urlQuery]);

  const submit = useCallback(
    (over: Partial<{ checkIn: string; checkOut: string; guestCount: number; roomCount: number }> = {}) => {
      const v = {
        checkIn: over.checkIn ?? checkIn,
        checkOut: over.checkOut ?? checkOut,
        guestCount: over.guestCount ?? guestCount,
        roomCount: over.roomCount ?? roomCount,
      };
      const nextErrors = validateSearchForm(v, todayLocal());
      setErrors(nextErrors);
      if (Object.keys(nextErrors).length > 0) return;
      const q = new URLSearchParams({
        checkIn: v.checkIn,
        checkOut: v.checkOut,
        guestCount: String(v.guestCount),
        roomCount: String(v.roomCount),
      });
      const hid = params.get("hotelId");
      if (hid) q.set("hotelId", hid); // 조건만 바꾸면 선택 호텔은 유지한다
      router.replace(`/search?${q}`);
    },
    [router, params, checkIn, checkOut, guestCount, roomCount],
  );

  const selectHotel = useCallback(
    (hotelId: number | null) => {
      const q = new URLSearchParams(urlQuery);
      if (hotelId === null) q.delete("hotelId");
      else q.set("hotelId", String(hotelId));
      router.replace(`/search?${q}`);
    },
    [router, urlQuery],
  );

  const selectedHotel =
    hotels.kind === "loaded" && selectedHotelId !== null
      ? hotels.hotels.find((h) => h.hotelId === selectedHotelId)
      : undefined;

  const filteredHotels = useMemo(() => {
    if (hotels.kind !== "loaded") return [];
    const kw = nameFilter.trim();
    return kw ? hotels.hotels.filter((h) => h.name.includes(kw)) : hotels.hotels;
  }, [hotels, nameFilter]);

  return (
    <>
      <h1 className="h1">묵을 곳을 찾습니다</h1>
      <p className="sub">날짜를 정하고 호텔을 고르면, 그 기간 내내 비어 있는 객실을 보여줍니다.</p>

      <form
        className="card card-pad"
        style={{ marginBottom: 16 }}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 0.6fr 0.6fr auto",
            gap: 12,
            alignItems: "end",
          }}
        >
          <div>
            <p className="label">체크인</p>
            <input
              ref={checkInRef}
              type="date"
              className={`field mono tnum${errors.checkIn ? " bad" : ""}`}
              value={checkIn}
              onChange={(e) => setCheckIn(e.target.value)}
              aria-label="체크인"
            />
          </div>
          <div>
            <p className="label">체크아웃</p>
            <input
              type="date"
              className={`field mono tnum${errors.checkOut ? " bad" : ""}`}
              value={checkOut}
              onChange={(e) => setCheckOut(e.target.value)}
              aria-label="체크아웃"
            />
          </div>
          <div>
            <p className="label">인원</p>
            <input
              type="number"
              min={1}
              max={20}
              className={`field tnum${errors.guestCount ? " bad" : ""}`}
              value={guestCount}
              onChange={(e) => setGuestCount(Number(e.target.value))}
              aria-label="인원"
            />
          </div>
          <div>
            <p className="label">객실 수</p>
            <input
              type="number"
              min={1}
              max={10}
              className={`field tnum${errors.roomCount ? " bad" : ""}`}
              value={roomCount}
              onChange={(e) => setRoomCount(Number(e.target.value))}
              aria-label="객실 수"
            />
          </div>
          <button className="btn brass" type="submit" style={{ height: 41 }}>
            검색
          </button>
        </div>
        {Object.values(errors).filter(Boolean).map((msg) => (
          <div className="field-error" key={msg}>{msg}</div>
        ))}
      </form>

      {!hasDates && (
        <p className="note" style={{ marginBottom: 14 }}>
          <span>ⓘ</span>
          <span>날짜를 넣고 검색하면 호텔을 고를 수 있습니다.</span>
        </p>
      )}

      {hasDates && !selectedHotel && wished.length > 0 && (
        <div className="card card-pad" style={{ marginBottom: 14 }}>
          <p className="label">찜한 객실</p>
          <div className="stack" style={{ gap: 8 }}>
            {wished.map((w) => (
              <div className="between" key={w.roomTypeId}>
                <div className="inline" style={{ gap: 8 }}>
                  <button
                    aria-label="찜 해제"
                    onClick={() => toggleWish(w)}
                    style={{ background: "none", border: 0, cursor: "pointer", fontSize: 16, color: "var(--brass)" }}
                  >
                    ♥
                  </button>
                  <b>{w.roomTypeName}</b>
                  <span className="note">{w.hotelName}</span>
                </div>
                <button className="btn ghost sm" onClick={() => selectHotel(w.hotelId)}>
                  잔여 조회
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasDates && !selectedHotel && (
        <HotelList
          state={hotels}
          filtered={filteredHotels}
          nameFilter={nameFilter}
          onFilter={setNameFilter}
          onSelect={selectHotel}
        />
      )}

      {hasDates && selectedHotel && (
        <SelectedHotel
          hotel={selectedHotel}
          avail={avail}
          wishedIds={new Set(wished.map((w) => w.roomTypeId))}
          onToggleWish={toggleWish}
          onBackToList={() => selectHotel(null)}
          onChangeDates={() => checkInRef.current?.focus()}
          onBackInRange={(until) => {
            const inDate = addDays(until, -1);
            const outDate = addDays(until, 1);
            setCheckIn(inDate);
            setCheckOut(outDate);
            submit({ checkIn: inDate, checkOut: outDate });
          }}
          onMoreRooms={() => {
            const next = roomCount + 1;
            setRoomCount(next);
            submit({ roomCount: next });
          }}
          onBook={(roomTypeId, extra) => {
            const q = new URLSearchParams({
              hotelId: String(selectedHotel.hotelId),
              hotelName: selectedHotel.name,
              roomTypeId: String(roomTypeId),
              ...extra,
              checkIn: params.get("checkIn") ?? "",
              checkOut: params.get("checkOut") ?? "",
              guestCount: params.get("guestCount") ?? "2",
              roomCount: params.get("roomCount") ?? "1",
            });
            router.push(`/book?${q}`);
          }}
        />
      )}
    </>
  );
}

// ---- 1단: 호텔 목록 (GET /api/hotels — 잔여 없음, 시드 기준 구성·정가) ----

function HotelList({
  state,
  filtered,
  nameFilter,
  onFilter,
  onSelect,
}: {
  state: HotelsState;
  filtered: HotelInfo[];
  nameFilter: string;
  onFilter: (v: string) => void;
  onSelect: (hotelId: number) => void;
}) {
  if (state.kind === "loading") {
    return (
      <div className="stack" role="status" aria-label="호텔 목록 불러오는 중">
        {[0, 1, 2].map((i) => (
          <div className="card card-pad between" key={i}>
            <div className="grow stack" style={{ gap: 8 }}>
              <div className="skel" style={{ width: 160, height: 16 }} />
              <div className="skel" style={{ width: 240, height: 12 }} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="card" role="alert">
        <div className="empty">
          <div className="big">호텔 목록을 불러오지 못했습니다</div>
          <p className="why">{state.body}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="between" style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>
          호텔 {state.hotels.length}곳 — 호텔을 고르면 그 호텔의 잔여·요금을 조회합니다
        </span>
        <input
          className="field"
          style={{ maxWidth: 220, padding: "7px 12px", fontSize: 13 }}
          placeholder="호텔 이름으로 찾기"
          value={nameFilter}
          onChange={(e) => onFilter(e.target.value)}
          aria-label="호텔 이름 필터"
        />
      </div>
      {filtered.length === 0 && (
        <div className="card"><div className="empty"><div className="big">이름에 맞는 호텔이 없습니다</div></div></div>
      )}
      <div className="stack" style={{ gap: 10 }}>
        {filtered.slice(0, 30).map((h) => {
          const minPrice = Math.min(...h.roomTypes.map((r) => r.basePrice));
          return (
            <div className="card card-pad between" key={h.hotelId} style={{ padding: "13px 18px" }}>
              <div className="grow">
                <b style={{ fontSize: 15 }}>{h.name}</b>
                <div style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>
                  {h.address} · 객실 {h.roomTypes.length}종
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 13 }} className="tnum">
                  1박 <b>{won(minPrice)}원~</b> <span className="note">(정가 기준)</span>
                </div>
                <button className="btn brass sm" style={{ marginTop: 6 }} onClick={() => onSelect(h.hotelId)}>
                  잔여 조회
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {filtered.length > 30 && (
        <p className="note" style={{ marginTop: 10 }}>
          <span>·</span>
          <span>{filtered.length - 30}곳 더 있습니다 — 이름으로 좁혀 주세요.</span>
        </p>
      )}
    </>
  );
}

// ---- 2단: 선택 호텔의 객실 목록 (GET /api/availability) ----

function SelectedHotel({
  hotel,
  avail,
  wishedIds,
  onToggleWish,
  onBackToList,
  onChangeDates,
  onBackInRange,
  onMoreRooms,
  onBook,
}: {
  hotel: HotelInfo;
  avail: AvailState;
  wishedIds: Set<number>;
  onToggleWish: (item: WishItem) => void;
  onBackToList: () => void;
  onChangeDates: () => void;
  onBackInRange: (until: string) => void;
  onMoreRooms: () => void;
  onBook: (roomTypeId: number, extra: Record<string, string>) => void;
}) {
  const head = (
    <div className="between" style={{ marginBottom: 10 }}>
      <div className="inline" style={{ gap: 10 }}>
        <button className="btn ghost sm" onClick={onBackToList}>← 호텔 목록</button>
        <b style={{ fontSize: 15 }}>{hotel.name}</b>
      </div>
    </div>
  );

  if (avail.kind === "loading" || avail.kind === "idle") {
    return (
      <>
        {head}
        <div className="stack" role="status" aria-label="잔여 조회 중">
          <div className="card card-pad between">
            <div className="grow stack" style={{ gap: 8 }}>
              <div className="skel" style={{ width: 130, height: 16 }} />
              <div className="skel" style={{ width: 220, height: 12 }} />
            </div>
            <div className="skel" style={{ width: 150, height: 38 }} />
          </div>
        </div>
      </>
    );
  }

  if (avail.kind === "error") {
    return (
      <>
        {head}
        <div className="card" role="alert">
          <div className="empty">
            <div className="big">잔여를 조회하지 못했습니다</div>
            <p className="why">{avail.body}</p>
            <div className="actions"><button className="btn ghost sm" onClick={onBackToList}>호텔 목록으로</button></div>
          </div>
        </div>
      </>
    );
  }

  const data = avail.data;
  const searchedAtLabel = (() => {
    const t = new Date(data.searchedAt);
    return Number.isNaN(t.getTime()) ? "" : t.toLocaleTimeString("ko-KR", { hour12: false });
  })();

  if (data.items.length === 0) {
    // 빈 결과 3종 — 다음 행동이 다르므로 문구·버튼이 다르다 (시안 S1)
    if (data.emptyReason === "NOT_YET_OPEN") {
      const until = data.salesOpenUntil ?? "";
      const untilLabel = until
        ? new Date(until).toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" })
        : "";
      return (
        <>
          {head}
          <div className="card"><div className="empty">
            <div className="big">아직 판매를 열지 않은 날짜입니다</div>
            <p className="why">
              {untilLabel && (<>현재 <b className="tnum">{untilLabel} 숙박분까지</b> 판매 중입니다. </>)}
              매진이 아니라 판매 전입니다.
            </p>
            <div className="actions">
              {until
                ? <button className="btn sm" onClick={() => onBackInRange(until)}>판매 중인 기간에서 찾기</button>
                : <button className="btn sm" onClick={onChangeDates}>날짜 바꾸기</button>}
            </div>
          </div></div>
        </>
      );
    }
    if (data.emptyReason === "NO_FITTING_ROOM_TYPE") {
      return (
        <>
          {head}
          <div className="card"><div className="empty">
            <div className="big">{data.guestCount}명이 함께 묵을 수 있는 객실이 없습니다</div>
            <p className="why"><b>객실 수를 늘리거나</b> 인원을 나눠 검색해 보세요.</p>
            <div className="actions">
              <button className="btn sm" onClick={onMoreRooms}>객실 {data.roomCount + 1}개로 다시 검색</button>
            </div>
          </div></div>
        </>
      );
    }
    return (
      <>
        {head}
        <div className="card"><div className="empty">
          <div className="big">이 기간은 매진되었습니다</div>
          <p className="why">{data.checkIn} ~ {data.checkOut} 사이에 남은 객실이 없습니다.</p>
          <div className="actions">
            <button className="btn sm" onClick={onChangeDates}>날짜 바꾸기</button>
            <button className="btn ghost sm" onClick={onBackToList}>다른 호텔 보기</button>
          </div>
        </div></div>
      </>
    );
  }

  return (
    <>
      <div className="between" style={{ marginBottom: 10 }}>
        <div className="inline" style={{ gap: 10 }}>
          <button className="btn ghost sm" onClick={onBackToList}>← 호텔 목록</button>
          <b style={{ fontSize: 15 }}>{hotel.name}</b>
          <span style={{ fontSize: 13, color: "var(--ink-soft)" }}>
            {data.nights}박 · {data.items.length}개 객실타입
          </span>
        </div>
        {searchedAtLabel && (
          <span className="badge mute plain mono tnum">
            {searchedAtLabel} 기준 · 최대 {data.staleToleranceSeconds}초 전 정보
          </span>
        )}
      </div>
      <div className="stack">
        {data.items.map((it) => {
          const low = it.minRemaining <= 5;
          return (
            <div
              className="card card-pad between"
              key={it.roomTypeId}
              style={low ? { borderColor: "var(--warn)" } : undefined}
            >
              <div className="grow">
                <div className="inline" style={{ gap: 8 }}>
                  <b style={{ fontSize: 15.5 }} className="serif">{it.roomTypeName}</b>
                  {low ? (
                    <span className="badge warn tnum">{it.minRemaining}실 남음</span>
                  ) : (
                    <span className="badge ok">여유</span>
                  )}
                  <button
                    aria-label={wishedIds.has(it.roomTypeId) ? "찜 해제" : "찜"}
                    onClick={() =>
                      onToggleWish({
                        hotelId: hotel.hotelId,
                        hotelName: hotel.name,
                        roomTypeId: it.roomTypeId,
                        roomTypeName: it.roomTypeName,
                      })
                    }
                    style={{ background: "none", border: 0, cursor: "pointer", fontSize: 17, color: "var(--brass)" }}
                  >
                    {wishedIds.has(it.roomTypeId) ? "♥" : "♡"}
                  </button>
                </div>
                <div style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>
                  1실 정원 {it.capacity}명 · 가장 적은 날 기준 <b className="tnum">{it.minRemaining}실</b>
                  {low && " — 조회 후 바뀌었을 수 있습니다"}
                </div>
              </div>
              <div style={{ textAlign: "right", minWidth: 170 }}>
                <div className="money tnum">{won(it.totalPrice)}<small>원</small></div>
                <div style={{ fontSize: 12, color: "var(--ink-faint)" }} className="tnum">
                  {data.nights}박 합계 · 1박 {won(it.pricePerNight)}원
                </div>
                <button
                  className="btn brass sm"
                  style={{ marginTop: 8 }}
                  onClick={() =>
                    onBook(it.roomTypeId, {
                      roomTypeName: it.roomTypeName,
                      capacity: String(it.capacity),
                      pricePerNight: String(it.pricePerNight),
                    })
                  }
                >
                  이 객실로 예약
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <p className="note" style={{ marginTop: 14 }}>
        <span>ⓘ</span>
        <span>
          잔여 수는 <b>조회한 순간의 값</b>입니다. 예약 버튼을 누르는 순간 서버가 다시 확인하며,
          그사이 다른 분이 먼저 예약하면 실패할 수 있습니다.
        </span>
      </p>
    </>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchScreen />
    </Suspense>
  );
}
