"use client";

// S1 객실 검색 — 시안 S1의 상태 6종(정상·로딩·빈 3종·오류)을 전부 다룬다.
// 검색 조건은 URL 쿼리가 진실이다(시안 D4) — 새로고침·뒤로가기·공유가 그대로 동작한다.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/backend";
import { messageForError } from "@/lib/error-messages";
import { HOTELS } from "@/lib/hotels";
import { validateSearchForm, type SearchFormErrors } from "@/lib/search-form";
import type { AvailabilityResponse } from "@/lib/contracts";

import { addDays, todayLocal } from "@/lib/dates";

function won(n: number): string {
  return n.toLocaleString("ko-KR");
}

type ScreenState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "results"; data: AvailabilityResponse }
  | { kind: "error"; title: string; body: string };

function SearchScreen() {
  const router = useRouter();
  const params = useSearchParams();

  // 폼 상태 — URL에 값이 있으면 그것으로 시작한다
  const [hotelId, setHotelId] = useState(Number(params.get("hotelId") ?? 1));
  const [checkIn, setCheckIn] = useState(params.get("checkIn") ?? "");
  const [checkOut, setCheckOut] = useState(params.get("checkOut") ?? "");
  const [guestCount, setGuestCount] = useState(Number(params.get("guestCount") ?? 2));
  const [roomCount, setRoomCount] = useState(Number(params.get("roomCount") ?? 1));
  const [errors, setErrors] = useState<SearchFormErrors>({});
  const [screen, setScreen] = useState<ScreenState>({ kind: "idle" });
  const checkInRef = useRef<HTMLInputElement>(null);

  const urlQuery = params.toString();

  // URL에 완결된 조건이 실려 있으면 검색을 실행한다 — 조건 변경은 전부 URL을 거친다
  useEffect(() => {
    const q = new URLSearchParams(urlQuery);
    const cIn = q.get("checkIn");
    const cOut = q.get("checkOut");
    if (!cIn || !cOut) return;
    const query = {
      hotelId: Number(q.get("hotelId") ?? 1),
      checkIn: cIn,
      checkOut: cOut,
      guestCount: Number(q.get("guestCount") ?? 2),
      roomCount: Number(q.get("roomCount") ?? 1),
    };
    let cancelled = false;
    setScreen({ kind: "loading" });
    api
      .searchAvailability(query)
      .then((data) => {
        if (!cancelled) setScreen({ kind: "results", data });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setScreen({ kind: "error", title: "검색하지 못했습니다", body: messageForError(e).body });
      });
    return () => {
      cancelled = true;
    };
  }, [urlQuery]);

  const submit = useCallback(
    (over: Partial<{ hotelId: number; checkIn: string; checkOut: string; guestCount: number; roomCount: number }> = {}) => {
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
        hotelId: String(over.hotelId ?? hotelId),
        checkIn: v.checkIn,
        checkOut: v.checkOut,
        guestCount: String(v.guestCount),
        roomCount: String(v.roomCount),
      });
      router.replace(`/search?${q}`);
    },
    [router, hotelId, checkIn, checkOut, guestCount, roomCount],
  );

  const searchedAtLabel = useMemo(() => {
    if (screen.kind !== "results") return "";
    const t = new Date(screen.data.searchedAt);
    return Number.isNaN(t.getTime())
      ? ""
      : t.toLocaleTimeString("ko-KR", { hour12: false });
  }, [screen]);

  return (
    <>
      <h1 className="h1">묵을 곳을 찾습니다</h1>
      <p className="sub">날짜와 인원을 넣으면 그 기간 내내 비어 있는 객실만 보여줍니다.</p>

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
            gridTemplateColumns: "1.5fr 1fr 1fr 0.7fr 0.7fr auto",
            gap: 12,
            alignItems: "end",
          }}
        >
          <div>
            <p className="label">호텔</p>
            <select
              className="field"
              value={hotelId}
              onChange={(e) => setHotelId(Number(e.target.value))}
              aria-label="호텔"
            >
              {HOTELS.map((h) => (
                <option key={h.id} value={h.id}>{h.name}</option>
              ))}
            </select>
          </div>
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
                <div className="skel" style={{ width: 130, height: 16 }} />
                <div className="skel" style={{ width: 220, height: 12 }} />
              </div>
              <div className="skel" style={{ width: 150, height: 38 }} />
            </div>
          ))}
        </div>
      )}

      {screen.kind === "results" && screen.data.items.length > 0 && (
        <>
          <div className="between" style={{ marginBottom: 10 }}>
            <span style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>
              {screen.data.nights}박 · {screen.data.items.length}개 객실타입
            </span>
            {searchedAtLabel && (
              <span className="badge mute plain mono tnum">
                {searchedAtLabel} 기준 · 최대 {screen.data.staleToleranceSeconds}초 전 정보
              </span>
            )}
          </div>
          <div className="stack">
            {screen.data.items.map((it) => {
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
                      {screen.data.nights}박 합계 · 1박 {won(it.pricePerNight)}원
                    </div>
                    <button
                      className="btn brass sm"
                      style={{ marginTop: 8 }}
                      onClick={() => {
                        const q = new URLSearchParams({
                          hotelId: String(screen.data.hotelId),
                          roomTypeId: String(it.roomTypeId),
                          roomTypeName: it.roomTypeName,
                          capacity: String(it.capacity),
                          pricePerNight: String(it.pricePerNight),
                          checkIn: screen.data.checkIn,
                          checkOut: screen.data.checkOut,
                          guestCount: String(screen.data.guestCount),
                          roomCount: String(screen.data.roomCount),
                        });
                        router.push(`/book?${q}`);
                      }}
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

      {screen.kind === "results" && screen.data.items.length === 0 && (
        <EmptyResult
          data={screen.data}
          onChangeDates={() => checkInRef.current?.focus()}
          onChangeHotel={() => {
            const other = hotelId === 1 ? 2 : 1;
            setHotelId(other);
            submit({ hotelId: other });
          }}
          onMoreRooms={() => {
            const next = roomCount + 1;
            setRoomCount(next);
            submit({ roomCount: next });
          }}
          onBackInRange={() => {
            // 하드코딩 대신 응답의 salesOpenUntil(판매 마지막 숙박일)로 계산한다
            const until = screen.data.salesOpenUntil;
            if (!until) return checkInRef.current?.focus();
            const inDate = addDays(until, -1);
            const outDate = addDays(until, 1); // 마지막 숙박일의 체크아웃은 다음 날
            setCheckIn(inDate);
            setCheckOut(outDate);
            submit({ checkIn: inDate, checkOut: outDate });
          }}
        />
      )}

      {screen.kind === "error" && (
        <div className="card" role="alert">
          <div className="empty">
            <div className="big">{screen.title}</div>
            <p className="why">{screen.body}</p>
            <div className="actions">
              <button className="btn sm" onClick={() => submit()}>다시 검색</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function EmptyResult({
  data,
  onChangeDates,
  onChangeHotel,
  onMoreRooms,
  onBackInRange,
}: {
  data: AvailabilityResponse;
  onChangeDates: () => void;
  onChangeHotel: () => void;
  onMoreRooms: () => void;
  onBackInRange: () => void;
}) {
  // 빈 결과 3종은 같은 빈 화면이 아니다 — 다음 행동이 달라서 문구와 버튼이 다르다 (시안 S1)
  if (data.emptyReason === "NOT_YET_OPEN") {
    const until = data.salesOpenUntil
      ? new Date(data.salesOpenUntil).toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" })
      : "";
    return (
      <div className="card">
        <div className="empty">
          <div className="big">아직 판매를 열지 않은 날짜입니다</div>
          <p className="why">
            {until && (
              <>현재 <b className="tnum">{until} 숙박분까지</b> 판매 중입니다. </>
            )}
            매진이 아니라 판매 전이므로, 그 이후 날짜는 열리면 예약할 수 있습니다.
          </p>
          <div className="actions">
            <button className="btn sm" onClick={onBackInRange}>판매 중인 기간에서 찾기</button>
          </div>
        </div>
      </div>
    );
  }
  if (data.emptyReason === "NO_FITTING_ROOM_TYPE") {
    return (
      <div className="card">
        <div className="empty">
          <div className="big">{data.guestCount}명이 함께 묵을 수 있는 객실이 없습니다</div>
          <p className="why">
            이 호텔의 가장 큰 객실은 1실 4명까지입니다. <b>객실 수를 늘리거나</b> 인원을 나눠
            검색해 보세요.
          </p>
          <div className="actions">
            <button className="btn sm" onClick={onMoreRooms}>
              객실 {data.roomCount + 1}개로 다시 검색
            </button>
          </div>
        </div>
      </div>
    );
  }
  // SOLD_OUT (emptyReason이 없으면 서버 판단을 그대로 매진으로 다룬다)
  return (
    <div className="card">
      <div className="empty">
        <div className="big">이 기간은 매진되었습니다</div>
        <p className="why">
          {data.checkIn} ~ {data.checkOut} 사이에 남은 객실이 없습니다. 날짜를 바꾸면 예약할 수
          있습니다.
        </p>
        <div className="actions">
          <button className="btn sm" onClick={onChangeDates}>날짜 바꾸기</button>
          <button className="btn ghost sm" onClick={onChangeHotel}>다른 호텔 보기</button>
        </div>
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchScreen />
    </Suspense>
  );
}
