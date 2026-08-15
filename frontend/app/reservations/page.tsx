"use client";

// 예약 확인 — 확인번호 직접 입력 + "내 예약" 목록 (관리자 지시 2026-08-16).
//
// F01에 목록 API가 없으므로(백엔드에 요구하지 않는다 — 시안 D7) 목록의 원천은
// 이 브라우저에 남긴 확인번호뿐이다. 상태·일정은 행마다 서버를 조회해 그린다 —
// 서버가 404를 주는 행(다른 식별값으로 만든 예약 등)은 숨긴다.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/backend";
import { createMyReservations } from "@/lib/my-reservations";
import { viewOf } from "@/lib/reservation-view";
import { useUserId } from "@/components/user-context";
import type { ReservationResponse } from "@/lib/contracts";

function won(n: number | undefined): string {
  return (n ?? 0).toLocaleString("ko-KR");
}

type MineState =
  | { kind: "loading" }
  | { kind: "loaded"; rows: ReservationResponse[] };

export default function ReservationLookupPage() {
  const router = useRouter();
  const { userId } = useUserId();
  const [code, setCode] = useState("");
  const [mine, setMine] = useState<MineState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setMine({ kind: "loading" });
    const codes = createMyReservations(window.localStorage).list(userId);
    if (codes.length === 0) {
      setMine({ kind: "loaded", rows: [] });
      return;
    }
    Promise.all(
      codes.map((c) => api.getReservation(c, userId).catch(() => null)), // 404 등은 숨긴다
    ).then((rows) => {
      if (!cancelled)
        setMine({ kind: "loaded", rows: rows.filter((r): r is ReservationResponse => r !== null) });
    });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  return (
    <>
      <h1 className="h1">예약 확인</h1>
      <p className="sub">확인번호를 입력하거나, 이 브라우저에서 만든 예약을 바로 여세요.</p>

      <form
        className="card card-pad inline"
        style={{ marginBottom: 18 }}
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = code.trim();
          if (trimmed) router.push(`/reservations/${encodeURIComponent(trimmed)}`);
        }}
      >
        <input
          className="field mono grow"
          style={{ maxWidth: 320 }}
          placeholder="예: 260901-H1R3-K7M2XQ4R"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          aria-label="확인번호"
        />
        <button className="btn brass" type="submit" disabled={!code.trim()}>
          조회
        </button>
      </form>

      <p className="label" style={{ marginBottom: 8 }}>내 예약 — 이 브라우저에서 만든 것</p>

      {mine.kind === "loading" && (
        <div className="card card-pad" role="status" aria-label="불러오는 중">
          <div className="skel" style={{ width: 260, height: 14 }} />
        </div>
      )}

      {mine.kind === "loaded" && mine.rows.length === 0 && (
        <div className="card card-pad">
          <p className="note">
            <span>·</span>
            <span>
              아직 없습니다. 예약을 만들면 여기 쌓입니다. 다른 브라우저·기기에서 만든 예약은
              보이지 않으니 확인번호로 조회해 주세요.
            </span>
          </p>
        </div>
      )}

      {mine.kind === "loaded" && mine.rows.length > 0 && (
        <div className="stack" style={{ gap: 10 }}>
          {mine.rows.map((r) => {
            const view = viewOf(r);
            return (
              <div className="card card-pad between" key={r.confirmationCode} style={{ padding: "13px 18px" }}>
                <div className="grow">
                  <div className="inline" style={{ gap: 8 }}>
                    <span className={`badge ${view.tone}`}>{view.badgeLabel}</span>
                    <span className="mono tnum" style={{ fontSize: 12.5, color: "var(--ink-faint)" }}>
                      {r.confirmationCode}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, color: "var(--ink-soft)" }} className="tnum">
                    {r.checkIn} → {r.checkOut} · {r.roomCount ?? 1}실 · {won(r.totalPrice)}원
                  </div>
                </div>
                <button
                  className="btn ghost sm"
                  onClick={() => router.push(`/reservations/${encodeURIComponent(r.confirmationCode)}`)}
                >
                  상세
                </button>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
