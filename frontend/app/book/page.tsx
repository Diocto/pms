"use client";

// S2 예약 주문서 — 시안 S2의 상태 4종.
// 이 화면이 지는 책임 둘: ① 멱등성 키를 여기서 만들고 성공할 때까지 유지한다.
// ② 409를 오류가 아니라 4단계 정상 흐름으로 처리한다 (booking-flow.ts).

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/backend";
import { ApiError } from "@/lib/api";
import { attemptBooking, type BookingPhase } from "@/lib/booking-flow";
import { ERROR_CODES } from "@/lib/contracts";
import { nightsBetween } from "@/lib/dates";
import { createMyReservations } from "@/lib/my-reservations";
import { messageForError } from "@/lib/error-messages";
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
    // hotelId도 필수다 — 없으면 기본값으로 메우지 않고 거부한다. 기본값 1로 메우면
    // 409 시 fresh 재검색이 엉뚱한 호텔을 본다 (리뷰 라운드1 중요-1)
    const hotelIdRaw = params.get("hotelId");
    if (!roomTypeId || !checkIn || !checkOut || !hotelIdRaw) return null;
    const nights = Math.max(1, nightsBetween(checkIn, checkOut));
    const roomCount = Number(params.get("roomCount") ?? 1);
    const pricePerNight = Number(params.get("pricePerNight") ?? 0);
    return {
      hotelId: Number(hotelIdRaw),
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
  // useState로 두어 화면에 보이는 "요청 번호"와 실제 전송 키가 항상 같은 값이 되게 한다.
  const [idemKey, setIdemKey] = useState<string>(() => crypto.randomUUID());
  const [screen, setScreen] = useState<ScreenState>({ kind: "idle" });

  // 사용자 식별값이 바뀌면 새 키 + 화면 초기화 — 서버의 중복 판정 키는
  // (X-User-Id, Idempotency-Key) 쌍이라 사용자가 바뀌면 "다른 예약 시도"다.
  // 이전 사용자의 오류·마감 카드("중복으로 잡히지 않습니다")를 남겨두면 그 약속이
  // 새 (사용자, 키) 쌍에서는 거짓이 된다 (라운드2 concurrency 제안).
  const firstUserRef = useRef(true);
  // 진행 중이던 submit의 응답이 사용자 전환 뒤에 완주해 이전 사용자의 결과 카드를
  // 되살리지 않도록, 요청 순번으로 낡은 연속을 폐기한다 (라운드3 concurrency 제안)
  const submitSeqRef = useRef(0);
  useEffect(() => {
    if (firstUserRef.current) {
      // 첫 실행은 건너뛴다(키는 useState 초기값 그대로). dev StrictMode에서는 effect가
      // 두 번 돌아 한 번 재발급되지만, 키가 state라 표시·전송이 함께 바뀌어 안전하다.
      firstUserRef.current = false;
      return;
    }
    setIdemKey(crypto.randomUUID());
    setScreen({ kind: "idle" });
    submitSeqRef.current += 1; // 이전 사용자의 진행 중 응답 무효화
  }, [userId]);

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
  // 마감 판정 후에도 버튼을 살려두면 없는 재고에 다시 부딪힌다 (리뷰 라운드1 제안)
  const locked = screen.kind === "phase" || screen.kind === "sold-out";

  async function submit() {
    const seq = ++submitSeqRef.current;
    const fresh = () => seq === submitSeqRef.current; // 사용자 전환·새 제출이 없었는가
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
            { userId, idempotencyKey: idemKey },
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
        onPhase: (phase) => {
          if (fresh()) setScreen({ kind: "phase", phase });
        },
      });
      if (!fresh()) return; // 그 사이 사용자가 바뀌었다 — 이 결과는 그리지 않는다

      if (outcome.kind === "created") {
        // "내 예약" 목록용으로 확인번호만 남긴다 — 상태는 항상 서버 조회로 그린다
        createMyReservations(window.localStorage).record(
          userId,
          outcome.reservation.confirmationCode,
        );
        // 멱등 재요청(200)도 신규(201)와 똑같이 상세로 간다
        router.push(`/reservations/${encodeURIComponent(outcome.reservation.confirmationCode)}`);
        return;
      }
      setScreen({ kind: "sold-out" });
    } catch (e) {
      if (!fresh()) return;
      const code = e instanceof ApiError ? e.code : "";
      const m = messageForError(e);
      setScreen({ kind: "error", code, title: m.title, body: m.body });
    }
  }

  return (
    <>
      <h1 className="h1">예약 내용을 확인해 주세요</h1>
      <p className="sub">아직 방이 잡히지 않았습니다. 예약 버튼을 눌러야 객실이 확보됩니다.</p>

      <div className="two-col">
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
            <div className="card card-pad" role="status" style={{ borderColor: "var(--warn)" }}>
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
            <div className="card card-pad" role="alert" style={{ borderColor: "var(--danger)" }}>
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
            <div className="card card-pad" role="alert" style={{ borderColor: "var(--warn)" }}>
              <div style={{ fontSize: 15.5, fontWeight: 700 }}>{screen.title}</div>
              <div style={{ fontSize: 13, color: "var(--ink-soft)", marginTop: 3 }}>{screen.body}</div>
              <div className="inline" style={{ marginTop: 12 }}>
                {(screen.code === ERROR_CODES.LOCK_ACQUISITION_FAILED ||
                  screen.code === ERROR_CODES.REQUEST_IN_PROGRESS) && (
                  // 같은 키로 그대로 재시도한다. REQUEST_IN_PROGRESS도 같은 키 재제출이
                  // 1순위 동선이다 — 새 키(재검색→새 주문서)로 유도하면 중복 예약이 된다
                  // (리뷰 라운드1 중요-3)
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
            disabled={locked}
            onClick={submit}
          >
            {screen.kind === "phase" ? "예약 처리 중…" : screen.kind === "sold-out" ? "마감됨" : "예약하기"}
          </button>
          <p className="note" style={{ marginTop: 11 }}>
            <span>ⓘ</span>
            <span>
              <b>여러 번 눌러도 예약은 한 건만 생깁니다.</b> 이 화면에 들어올 때 발급된 요청
              번호로 같은 요청을 알아봅니다.
            </span>
          </p>
          <div style={{ marginTop: 7, fontSize: 11, color: "var(--ink-faint)" }} className="mono">
            요청 번호 {idemKey}
          </div>
        </div>
      </div>
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
