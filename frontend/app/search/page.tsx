"use client";

// S1 객실 검색 — 2단 구조 (관리자 지시 2026-08-16 개선).
// 검색하면 호텔 목록을 먼저 보여주고, 호텔을 눌러 그 호텔의 객실을 고른다.
//
// 검색 API는 hotelId가 필수라(F03 계약 — 백엔드에 변경을 요구하지 않는다) 호텔 목록은
// 시드 2곳을 병렬 조회해 조립한다. 조건·선택 호텔은 전부 URL 쿼리가 진실이다(시안 D4).

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/backend";
import { addDays, todayLocal } from "@/lib/dates";
import { messageForError } from "@/lib/error-messages";
import { HOTELS } from "@/lib/hotels";
import { summarizeHotel } from "@/lib/hotel-summary";
import { validateSearchForm, type SearchFormErrors } from "@/lib/search-form";
import type { AvailabilityResponse } from "@/lib/contracts";

function won(n: number): string {
  return n.toLocaleString("ko-KR");
}

interface HotelEntry {
  hotelId: number;
  hotelName: string;
  result: { kind: "ok"; data: AvailabilityResponse } | { kind: "error"; body: string };
}

type ScreenState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "results"; entries: HotelEntry[] };

function SearchScreen() {
  const router = useRouter();
  const params = useSearchParams();

  const [checkIn, setCheckIn] = useState(params.get("checkIn") ?? "");
  const [checkOut, setCheckOut] = useState(params.get("checkOut") ?? "");
  const [guestCount, setGuestCount] = useState(Number(params.get("guestCount") ?? 2));
  const [roomCount, setRoomCount] = useState(Number(params.get("roomCount") ?? 1));
  const [errors, setErrors] = useState<SearchFormErrors>({});
  const [screen, setScreen] = useState<ScreenState>({ kind: "idle" });
  const checkInRef = useRef<HTMLInputElement>(null);

  const urlQuery = params.toString();
  const selectedHotelId = params.get("hotelId") ? Number(params.get("hotelId")) : null;

  // URL에 완결된 조건이 실려 있으면 두 호텔을 병렬 조회한다
  useEffect(() => {
    const q = new URLSearchParams(urlQuery);
    const cIn = q.get("checkIn");
    const cOut = q.get("checkOut");
    if (!cIn || !cOut) return;
    const base = {
      checkIn: cIn,
      checkOut: cOut,
      guestCount: Number(q.get("guestCount") ?? 2),
      roomCount: Number(q.get("roomCount") ?? 1),
    };
    let cancelled = false;
    setScreen({ kind: "loading" });
    Promise.all(
      HOTELS.map(async (h): Promise<HotelEntry> => {
        try {
          const data = await api.searchAvailability({ hotelId: h.id, ...base });
          return { hotelId: h.id, hotelName: h.name, result: { kind: "ok", data } };
        } catch (e) {
          return {
            hotelId: h.id,
            hotelName: h.name,
            result: { kind: "error", body: messageForError(e).body },
          };
        }
      }),
    ).then((entries) => {
      if (!cancelled) setScreen({ kind: "results", entries });
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
      // 조건을 새로 검색하면 호텔 선택은 푼다 — 호텔 목록부터 다시 고른다
      const q = new URLSearchParams({
        checkIn: v.checkIn,
        checkOut: v.checkOut,
        guestCount: String(v.guestCount),
        roomCount: String(v.roomCount),
      });
      router.replace(`/search?${q}`);
    },
    [router, checkIn, checkOut, guestCount, roomCount],
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

  const selectedEntry =
    screen.kind === "results" && selectedHotelId !== null
      ? screen.entries.find((e) => e.hotelId === selectedHotelId)
      : undefined;

  const searchedAtLabel = useMemo(() => {
    if (screen.kind !== "results") return "";
    const ok = (selectedEntry ?? screen.entries.find((e) => e.result.kind === "ok"))?.result;
    if (!ok || ok.kind !== "ok") return "";
    const t = new Date(ok.data.searchedAt);
    return Number.isNaN(t.getTime()) ? "" : t.toLocaleTimeString("ko-KR", { hour12: false });
  }, [screen, selectedEntry]);

  return (
    <>
      <h1 className="h1">묵을 곳을 찾습니다</h1>
      <p className="sub">날짜와 인원을 넣으면 예약 가능한 호텔부터 보여줍니다.</p>

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

      {screen.kind === "loading" && (
        <div className="stack" role="status" aria-label="검색 중">
          {[0, 1].map((i) => (
            <div className="card card-pad between" key={i}>
              <div className="grow stack" style={{ gap: 8 }}>
                <div className="skel" style={{ width: 150, height: 16 }} />
                <div className="skel" style={{ width: 230, height: 12 }} />
              </div>
              <div className="skel" style={{ width: 130, height: 38 }} />
            </div>
          ))}
        </div>
      )}

      {screen.kind === "results" && !selectedEntry && (
        <HotelList
          entries={screen.entries}
          searchedAtLabel={searchedAtLabel}
          onSelect={(id) => selectHotel(id)}
          onChangeDates={() => checkInRef.current?.focus()}
          onMoreRooms={() => {
            const next = roomCount + 1;
            setRoomCount(next);
            submit({ roomCount: next });
          }}
          onBackInRange={(until) => {
            const inDate = addDays(until, -1);
            const outDate = addDays(until, 1);
            setCheckIn(inDate);
            setCheckOut(outDate);
            submit({ checkIn: inDate, checkOut: outDate });
          }}
        />
      )}

      {screen.kind === "results" && selectedEntry && (
        <SelectedHotel
          entry={selectedEntry}
          searchedAtLabel={searchedAtLabel}
          onBackToList={() => selectHotel(null)}
          onChangeDates={() => checkInRef.current?.focus()}
          onBook={(roomTypeId, extra) => {
            const ok = selectedEntry.result;
            if (ok.kind !== "ok") return;
            const q = new URLSearchParams({
              hotelId: String(selectedEntry.hotelId),
              roomTypeId: String(roomTypeId),
              ...extra,
              checkIn: ok.data.checkIn,
              checkOut: ok.data.checkOut,
              guestCount: String(ok.data.guestCount),
              roomCount: String(ok.data.roomCount),
            });
            router.push(`/book?${q}`);
          }}
        />
      )}
    </>
  );
}

// ---- 호텔 목록 (1단) ----

function HotelList({
  entries,
  searchedAtLabel,
  onSelect,
  onChangeDates,
  onMoreRooms,
  onBackInRange,
}: {
  entries: HotelEntry[];
  searchedAtLabel: string;
  onSelect: (hotelId: number) => void;
  onChangeDates: () => void;
  onMoreRooms: () => void;
  onBackInRange: (until: string) => void;
}) {
  const okEntries = entries.filter((e) => e.result.kind === "ok");

  // 두 호텔 모두 같은 "호텔과 무관한" 이유로 비면 목록 대신 안내 하나로 접는다 —
  // 판매 전·인원 초과는 날짜·인원의 문제라 호텔 구분이 정보가 아니다
  if (okEntries.length === entries.length) {
    const summaries = okEntries.map((e) =>
      e.result.kind === "ok" ? summarizeHotel(e.result.data) : null,
    );
    const first = okEntries[0].result;
    if (summaries.every((s) => s?.kind === "NOT_YET_OPEN") && first.kind === "ok") {
      const until = first.data.salesOpenUntil ?? "";
      const untilLabel = until
        ? new Date(until).toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" })
        : "";
      return (
        <div className="card">
          <div className="empty">
            <div className="big">아직 판매를 열지 않은 날짜입니다</div>
            <p className="why">
              {untilLabel && (
                <>현재 <b className="tnum">{untilLabel} 숙박분까지</b> 판매 중입니다. </>
              )}
              매진이 아니라 판매 전이므로, 그 이후 날짜는 열리면 예약할 수 있습니다.
            </p>
            <div className="actions">
              {until ? (
                <button className="btn sm" onClick={() => onBackInRange(until)}>
                  판매 중인 기간에서 찾기
                </button>
              ) : (
                <button className="btn sm" onClick={onChangeDates}>날짜 바꾸기</button>
              )}
            </div>
          </div>
        </div>
      );
    }
    if (summaries.every((s) => s?.kind === "NO_FITTING_ROOM_TYPE") && first.kind === "ok") {
      return (
        <div className="card">
          <div className="empty">
            <div className="big">{first.data.guestCount}명이 함께 묵을 수 있는 객실이 없습니다</div>
            <p className="why">
              가장 큰 객실이 1실 4명까지입니다. <b>객실 수를 늘리거나</b> 인원을 나눠 검색해
              보세요.
            </p>
            <div className="actions">
              <button className="btn sm" onClick={onMoreRooms}>
                객실 {first.data.roomCount + 1}개로 다시 검색
              </button>
            </div>
          </div>
        </div>
      );
    }
  }

  return (
    <>
      <div className="between" style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>
          호텔 {entries.length}곳 · 호텔을 선택하면 객실을 보여드립니다
        </span>
        {searchedAtLabel && (
          <span className="badge mute plain mono tnum">
            {searchedAtLabel} 기준 · 최대 10초 전 정보
          </span>
        )}
      </div>
      <div className="stack">
        {entries.map((e) => {
          if (e.result.kind === "error") {
            return (
              <div className="card card-pad between" key={e.hotelId} style={{ opacity: 0.75 }}>
                <div className="grow">
                  <div className="inline" style={{ gap: 8 }}>
                    <b style={{ fontSize: 15.5 }}>{e.hotelName}</b>
                    <span className="badge mute">확인 불가</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>{e.result.body}</div>
                </div>
              </div>
            );
          }
          const s = summarizeHotel(e.result.data);
          const clickable = s.kind === "available" || s.kind === "SOLD_OUT";
          return (
            <div
              className="card card-pad between"
              key={e.hotelId}
              style={s.kind === "available" ? undefined : { opacity: 0.66 }}
            >
              <div className="grow">
                <div className="inline" style={{ gap: 8 }}>
                  <b style={{ fontSize: 15.5 }}>{e.hotelName}</b>
                  {s.kind === "available" && <span className="badge ok">예약 가능</span>}
                  {s.kind === "SOLD_OUT" && <span className="badge danger">이 기간 만실</span>}
                  {s.kind === "NOT_YET_OPEN" && <span className="badge info">판매 전</span>}
                  {s.kind === "NO_FITTING_ROOM_TYPE" && (
                    <span className="badge mute">인원에 맞는 방 없음</span>
                  )}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>
                  {s.kind === "available"
                    ? <>예약 가능한 객실 {s.roomTypeCount}종</>
                    : s.kind === "SOLD_OUT"
                      ? "이 기간에 남은 객실이 없습니다 — 날짜를 바꾸면 예약할 수 있습니다"
                      : "조건을 바꾸면 예약할 수 있습니다"}
                </div>
              </div>
              <div style={{ textAlign: "right", minWidth: 170 }}>
                {s.kind === "available" && (
                  <>
                    <div className="money tnum">
                      {won(s.minTotalPrice)}<small>원~</small>
                    </div>
                    <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>총액 기준 최저가</div>
                  </>
                )}
                {clickable ? (
                  <button
                    className={`btn sm${s.kind === "available" ? " brass" : " ghost"}`}
                    style={{ marginTop: 8 }}
                    onClick={() => onSelect(e.hotelId)}
                  >
                    객실 보기
                  </button>
                ) : (
                  <button className="btn sm" disabled style={{ marginTop: 8 }}>
                    선택 불가
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

// ---- 선택한 호텔의 객실 목록 (2단) ----

function SelectedHotel({
  entry,
  searchedAtLabel,
  onBackToList,
  onChangeDates,
  onBook,
}: {
  entry: HotelEntry;
  searchedAtLabel: string;
  onBackToList: () => void;
  onChangeDates: () => void;
  onBook: (roomTypeId: number, extra: Record<string, string>) => void;
}) {
  if (entry.result.kind === "error") {
    return (
      <div className="card" role="alert">
        <div className="empty">
          <div className="big">검색하지 못했습니다</div>
          <p className="why">{entry.result.body}</p>
          <div className="actions">
            <button className="btn ghost sm" onClick={onBackToList}>호텔 목록으로</button>
          </div>
        </div>
      </div>
    );
  }
  const data = entry.result.data;

  return (
    <>
      <div className="between" style={{ marginBottom: 10 }}>
        <div className="inline" style={{ gap: 10 }}>
          <button className="btn ghost sm" onClick={onBackToList}>← 호텔 목록</button>
          <b style={{ fontSize: 15 }}>{entry.hotelName}</b>
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

      {data.items.length === 0 ? (
        <div className="card">
          <div className="empty">
            <div className="big">이 기간은 매진되었습니다</div>
            <p className="why">
              {data.checkIn} ~ {data.checkOut} 사이에 남은 객실이 없습니다. 날짜를 바꾸거나 다른
              호텔을 보세요.
            </p>
            <div className="actions">
              <button className="btn sm" onClick={onChangeDates}>날짜 바꾸기</button>
              <button className="btn ghost sm" onClick={onBackToList}>호텔 목록으로</button>
            </div>
          </div>
        </div>
      ) : (
        <>
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
                      <b style={{ fontSize: 15.5 }}>{it.roomTypeName}</b>
                      {low ? (
                        <span className="badge warn tnum">{it.minRemaining}실 남음</span>
                      ) : (
                        <span className="badge ok">여유</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--ink-soft)" }}>
                      1실 정원 {it.capacity}명 · 가장 적은 날 기준{" "}
                      <b className="tnum">{it.minRemaining}실</b>
                      {low && " — 조회 후 바뀌었을 수 있습니다"}
                    </div>
                  </div>
                  <div style={{ textAlign: "right", minWidth: 170 }}>
                    <div className="money tnum">
                      {won(it.totalPrice)}<small>원</small>
                    </div>
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
              잔여 수는 <b>조회한 순간의 값</b>입니다. 예약 버튼을 누르는 순간 서버가 다시
              확인하며, 그사이 다른 분이 먼저 예약하면 실패할 수 있습니다.
            </span>
          </p>
        </>
      )}
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
