"use client";

// 내 예약 — 서버가 진실 (관리자 지시: user_id로 DB에서 조회 / PR #38 목록 API).
// 상단의 사용자 식별값(X-User-Id)으로 GET /api/reservations를 호출해 목록을 그린다.
// 탭: 전체 / 결제 완료(CONFIRMED — 서버 status 필터) / 결제 대기 / 지난 내역(클라이언트 구분).

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/backend";
import { messageForError } from "@/lib/error-messages";
import { viewOf } from "@/lib/reservation-view";
import { useUserId } from "@/components/user-context";
import type { ReservationResponse, ReservationStatus } from "@/lib/contracts";

function won(n: number | undefined): string {
  return (n ?? 0).toLocaleString("ko-KR");
}

type Tab = "all" | "confirmed" | "pending" | "past";
const PAST: ReservationStatus[] = ["CHECKED_OUT", "CANCELLED", "EXPIRED"];

type ListState =
  | { kind: "loading" }
  | { kind: "loaded"; rows: ReservationResponse[] }
  | { kind: "error"; body: string };

export default function ReservationListPage() {
  const router = useRouter();
  const { userId } = useUserId();
  const [code, setCode] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const reqSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqSeqRef.current;
    setList({ kind: "loading" });
    try {
      // 결제 완료 탭만 서버 필터를 쓴다 — 관리자 지시의 "결제 완료 건 조회"가 이 경로다
      const rows =
        tab === "confirmed"
          ? await api.listReservations(userId, "CONFIRMED")
          : await api.listReservations(userId);
      if (seq !== reqSeqRef.current) return;
      const filtered =
        tab === "pending"
          ? rows.filter((r) => r.status === "PENDING")
          : tab === "past"
            ? rows.filter((r) => PAST.includes(r.status))
            : rows;
      setList({ kind: "loaded", rows: filtered });
    } catch (e) {
      if (seq !== reqSeqRef.current) return;
      setList({ kind: "error", body: messageForError(e).body });
    }
  }, [userId, tab]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <h1 className="h1">내 예약</h1>
      <p className="sub">
        사용자 식별값 <b className="mono">{userId}</b>(으)로 서버에서 조회합니다 — 상단에서
        식별값을 바꾸면 그 사용자의 예약이 보입니다. 로그인이 아닙니다.
      </p>

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
          placeholder="확인번호로 직접 조회"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          aria-label="확인번호"
        />
        <button className="btn brass" type="submit" disabled={!code.trim()}>
          조회
        </button>
      </form>

      <div className="inline" style={{ gap: 6, marginBottom: 12 }}>
        {(
          [
            ["all", "전체"],
            ["confirmed", "결제 완료"],
            ["pending", "결제 대기"],
            ["past", "지난 내역"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            className={`btn sm ${tab === key ? "" : "ghost"}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {list.kind === "loading" && (
        <div className="card card-pad" role="status" aria-label="불러오는 중">
          <div className="skel" style={{ width: 260, height: 14 }} />
        </div>
      )}

      {list.kind === "error" && (
        <div className="card" role="alert">
          <div className="empty">
            <div className="big">목록을 불러오지 못했습니다</div>
            <p className="why">{list.body}</p>
            <div className="actions">
              <button className="btn sm" onClick={() => void load()}>다시 불러오기</button>
            </div>
          </div>
        </div>
      )}

      {list.kind === "loaded" && list.rows.length === 0 && (
        <div className="card card-pad">
          <p className="note">
            <span>·</span>
            <span>
              이 식별값으로 만든 예약이 {tab === "all" ? "아직 없습니다" : "이 상태에는 없습니다"}.
              객실을 검색해 예약해 보세요.
            </span>
          </p>
        </div>
      )}

      {list.kind === "loaded" && list.rows.length > 0 && (
        <div className="stack" style={{ gap: 10 }}>
          {list.rows.map((r) => {
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
