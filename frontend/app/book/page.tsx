"use client";

// S2 예약 주문서 — 시안 S2의 상태 4종.
// 이 화면이 지는 책임 둘: ① 멱등성 키를 여기서 만들고 성공할 때까지 유지한다.
// ② 409를 오류가 아니라 4단계 정상 흐름으로 처리한다 (booking-flow.ts).

import { Suspense, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/backend";
import { ApiError } from "@/lib/api";
import { attemptBooking, type BookingPhase } from "@/lib/booking-flow";
import { ERROR_CODES } from "@/lib/contracts";
import { messageFor } from "@/lib/error-messages";
import { HOTELS } from "@/lib/hotels";
import { useUserId } from "@/components/user-context";

function won(n: number): string {
  return n.toLocaleString("ko-KR");
}

type ScreenState =
  | { kind: "idle" }
  | { kind: "phase"; phase: BookingPhase }
  | { kind: "sold-out" }
  | { kind: "error"; code: string; title: string; body: string };

function BookScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const { userId } = useUserId();

  const order = useMemo(() => {
    const roomTypeId = Number(params.get("roomTypeId"));
    const checkIn = params.get("checkIn") ?? "";
    const checkOut = params.get("checkOut") ?? "";
    if (!roomTypeId || !checkIn || !checkOut) return null;
    const nights = Math.max(
      1,
      Math.round((Date.parse(checkOut) - Date.parse(checkIn)) / 86_400_000),
    );
    const roomCount = Number(params.get("roomCount") ?? 1);
    const pricePerNight = Number(params.get("pricePerNight") ?? 0);
    return {
      hotelId: Number(params.get("hotelId") ?? 1),
      roomTypeId,
      roomTypeName: params.get("roomTypeName") ?? `객실타입 ${roomTypeId}`,
      capacity: Number(params.get("capacity") ?? 0),
      checkIn,
      checkOut,
      nights,
      guestCount: Number(params.get("guestCount") ?? 2),
      roomCount,
      pricePerNight,
      totalEstimate: pricePerNight * nights * roomCount,
    };
  }, [params]);

  // 멱등성 키 — 화면에 들어올 때 1회 발급. 연타·재시도 전부 같은 키로 나간다.
  // 성공하면 이 화면을 떠나므로 자연히 폐기된다. 입력은 이 화면에서 바뀌지 않는다
  // (조건 변경은 검색으로 돌아가서 하고, 그러면 새 화면 = 새 키다). 시안 D6.
  const idemKeyRef = useRef<string>(crypto.randomUUID());
  const [screen, setScreen] = useState<ScreenState>({ kind: "idle" });

  if (!order) {
    return (
      <div className="card">
        <div className="empty">
          <div className="big">예약할 객실이 선택되지 않았습니다</div>
          <p className="why">검색에서 객실을 선택하면 이 화면으로 옵니다.</p>
          <div className="actions">
            <button className="btn sm" onClick={() => router.push("/search")}>객실 검색으로</button>
          </div>
        </div>
      </div>
    );
  }

  const hotelName = HOTELS.find((h) => h.id === order.hotelId)?.name ?? "";
  const busy = screen.kind === "phase";

  async function submit() {
    try {
      const outcome = await attemptBooking({
        create: () =>
          api.createReservation(
            {
              roomTypeId: order!.roomTypeId,
              checkIn: order!.checkIn,
              checkOut: order!.checkOut,
              roomCount: order!.roomCount,
              guestCount: order!.guestCount,
            },
            { userId, idempotencyKey: idemKeyRef.current },
          ),
        checkFresh: async () => {
          const fresh = await api.searchAvailability(
            {
              hotelId: order!.hotelId,
              checkIn: order!.checkIn,
              checkOut: order!.checkOut,
              guestCount: order!.guestCount,
              roomCount: order!.roomCount,
            },
            { fresh: true },
          );
          const item = fresh.items.find((i) => i.roomTypeId === order!.roomTypeId);
          return item !== undefined && item.minRemaining >= order!.roomCount;
        },
        onPhase: (phase) => setScreen({ kind: "phase", phase }),
      });

      if (outcome.kind === "created") {
        // 멱등 재요청(200)도 신규(201)와 똑같이 상세로 간다
        router.push(`/reservations/${encodeURIComponent(outcome.reservation.confirmationCode)}`);
        return;
      }
      setScreen({ kind: "sold-out" });
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "UNKNOWN";
      const traceId = e instanceof ApiError ? e.traceId : undefined;
      const m = messageFor(code, traceId);
      setScreen({ kind: "error", code, title: m.title, body: m.body });
    }
  }

  return (
    <>
      <h1 className="h1">예약 내용을 확인해 주세요</h1>
      <p className="sub">아직 방이 잡히지 않았습니다. 예약 버튼을 눌러야 객실이 확보됩니다.</p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }} className="book-grid">
        <div className="stack">
          <div className="card card-pad">
            <p className="label">투숙 정보</p>
            <div style={{ fontSize: 16, fontWeight: 700 }}>
              {hotelName} · {order.roomTypeName}
            </div>
            <div style={{ fontSize: 13.5, color: "var(--ink-soft)" }} className="tnum">
              {order.checkIn} → {order.checkOut} · {order.nights}박 · 객실 {order.roomCount} · 성인{" "}
              {order.guestCount}
            </div>
            <hr className="divide" />
            <div className="row">
              <span>1실 정원</span>
              <b>
                {order.capacity}명 (요청 인원 {order.guestCount}명 —{" "}
                {order.guestCount <= order.capacity * order.roomCount ? "가능" : "초과"})
              </b>
            </div>
            <div className="row"><span>결제 유예</span><b>예약 후 10분</b></div>
            <p className="note" style={{ marginTop: 10 }}>
              <span>ⓘ</span>
              <span>
                예약을 만들면 방이 <b>10분간</b> 잡히고, 그 안에 결제하지 않으면 자동으로 풀려
                다시 판매됩니다.
              </span>
            </p>
          </div>

          {screen.kind === "phase" && screen.phase.kind !== "submitting" && (
            <div className="card card-pad" style={{ borderColor: "var(--warn)" }}>
              <div className="inline" style={{ gap: 8, marginBottom: 6 }}>
                <span className="badge warn">방금 마감됨</span>
              </div>
              <div style={{ fontSize: 15.5, fontWeight: 700 }}>방금 다른 분이 먼저 예약했습니다</div>
              <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 3 }}>
                결제는 진행되지 않았습니다.{" "}
                {screen.phase.kind === "checking-fresh"
                  ? "최신 재고를 확인하고 있습니다…"
                  : "남은 객실로 다시 시도하고 있습니다…"}
              </div>
              <div className="meter" style={{ marginTop: 12 }}>
                <span style={{ width: screen.phase.kind === "checking-fresh" ? "45%" : "75%" }} />
              </div>
              <div style={{ fontSize: 11.5, color: "var(--ink-faint)", marginTop: 6 }} className="tnum">
                자동 재시도 {screen.phase.attempt} / 2
              </div>
            </div>
          )}

          {screen.kind === "sold-out" && (
            <div className="card card-pad" style={{ borderColor: "var(--danger)" }}>
              <div className="inline" style={{ gap: 8, marginBottom: 6 }}>
                <span className="badge danger">마감</span>
              </div>
              <div style={{ fontSize: 15.5, fontWeight: 700 }}>이 조건은 마감되었습니다</div>
              <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 3 }}>
                두 차례 다시 시도했지만 남은 객실이 없습니다. 결제는 진행되지 않았습니다.
              </div>
              <div className="inline" style={{ marginTop: 12 }}>
                <button
                  className="btn sm"
                  onClick={() => {
                    const q = new URLSearchParams({
                      hotelId: String(order.hotelId),
                      checkIn: order.checkIn,
                      checkOut: order.checkOut,
                      guestCount: String(order.guestCount),
                      roomCount: String(order.roomCount),
                    });
                    router.push(`/search?${q}`);
                  }}
                >
                  다른 객실·날짜 보기
                </button>
              </div>
            </div>
          )}

          {screen.kind === "error" && (
            <div className="card card-pad" style={{ borderColor: "var(--warn)" }}>
              <div style={{ fontSize: 15.5, fontWeight: 700 }}>{screen.title}</div>
              <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 3 }}>{screen.body}</div>
              <div className="inline" style={{ marginTop: 12 }}>
                {screen.code === ERROR_CODES.LOCK_ACQUISITION_FAILED && (
                  // 혼잡은 같은 키로 그대로 재시도한다 — 입력은 남아 있다
                  <button className="btn sm" onClick={submit}>다시 시도</button>
                )}
                <button className="btn ghost sm" onClick={() => router.push("/search")}>
                  검색으로 돌아가기
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="card card-pad" style={{ alignSelf: "start" }}>
          <p className="label">요금</p>
          {order.pricePerNight > 0 ? (
            <>
              <div className="row">
                <span className="tnum">
                  {won(order.pricePerNight)}원 × {order.nights}박 × {order.roomCount}실
                </span>
                <b className="tnum">{won(order.totalEstimate)}원</b>
              </div>
              <hr className="divide" />
              <div className="between">
                <b style={{ fontSize: 14 }}>결제 예정</b>
                <div className="money tnum">
                  {won(order.totalEstimate)}<small>원</small>
                </div>
              </div>
            </>
          ) : (
            <div className="row"><span>금액</span><b>예약 생성 시 확정</b></div>
          )}
          <button
            className="btn brass"
            style={{ width: "100%", marginTop: 14 }}
            disabled={busy}
            onClick={submit}
          >
            {busy ? "예약 처리 중…" : "예약하기"}
          </button>
          <p className="note" style={{ marginTop: 11 }}>
            <span>ⓘ</span>
            <span>
              <b>여러 번 눌러도 예약은 한 건만 생깁니다.</b> 이 화면에 들어올 때 발급된 요청
              번호로 같은 요청을 알아봅니다.
            </span>
          </p>
          <div style={{ marginTop: 7, fontSize: 11, color: "var(--ink-faint)" }} className="mono">
            요청 번호 {idemKeyRef.current}
          </div>
        </div>
      </div>
      <style>{`@media (max-width: 760px) { .book-grid { grid-template-columns: 1fr !important; } }`}</style>
    </>
  );
}

export default function BookPage() {
  return (
    <Suspense>
      <BookScreen />
    </Suspense>
  );
}
