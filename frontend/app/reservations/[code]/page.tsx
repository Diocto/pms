"use client";

// S3 예약 상세 — 시안 S3의 상태 6종을 한 화면의 여섯 모습으로 그린다.
// 규칙 셋:
// - 행동 버튼은 reservation-view.ts의 매핑에서만 나온다.
// - confirm의 200 + CANCELLED(결제 거절)는 성공 화면이 아니다 — 본문 status로 분기.
// - 409(INVALID_STATE_TRANSITION)와 카운트다운 0은 둘 다 "재조회 후 서버의 진실을
//   그린다"로 수렴한다. 화면은 만료를 스스로 판정하지 않는다.

import { use, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/backend";
import { ApiError } from "@/lib/api";
import { ERROR_CODES, type ReservationResponse } from "@/lib/contracts";
import { computeRemainingSeconds, expiryFireDelayMs, formatMmSs } from "@/lib/countdown";
import { clampStayFrom, todayLocal } from "@/lib/dates";
import { messageFor, messageForError } from "@/lib/error-messages";
import { hotelIdOfRoomType } from "@/lib/hotels";
import { viewOf } from "@/lib/reservation-view";
import { ReviewSection } from "@/components/review-section";
import { useUserId } from "@/components/user-context";

function won(n: number | undefined): string {
  return (n ?? 0).toLocaleString("ko-KR");
}

type ScreenState =
  | { kind: "loading" }
  | { kind: "loaded"; r: ReservationResponse }
  | { kind: "not-found" }
  | { kind: "error"; title: string; body: string };

export default function ReservationDetailPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code: rawCode } = use(params);
  const code = decodeURIComponent(rawCode);
  const router = useRouter();
  const { userId } = useUserId();

  const [screen, setScreen] = useState<ScreenState>({ kind: "loading" });
  const [acting, setActing] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  // 상태 충돌(409) 후 재조회로 수렴했을 때 사용자에게 남기는 일회성 안내 (라운드1 제안)
  const [notice, setNotice] = useState<string | null>(null);
  // 재조회마다 증가 — Countdown을 재시작시켜 새 응답 기준으로 다시 계산하게 한다 (라운드1 제안)
  const [loadSeq, setLoadSeq] = useState(0);
  // 요청 순번 — 늦게 도착한 낡은 응답이 최신 화면을 덮어쓰지 않게 한다 (라운드2 제안).
  // 카운트다운 0의 자동 재조회와 사용자의 결제·취소가 겹칠 수 있다.
  const reqSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqSeqRef.current;
    try {
      const r = await api.getReservation(code, userId);
      if (seq !== reqSeqRef.current) return; // 더 새 요청이 나갔다 — 이 응답은 버린다
      setScreen({ kind: "loaded", r });
      setLoadSeq((v) => v + 1);
    } catch (e) {
      if (seq !== reqSeqRef.current) return;
      if (e instanceof ApiError && e.code === ERROR_CODES.RESOURCE_NOT_FOUND) {
        setScreen({ kind: "not-found" });
        return;
      }
      const m = messageForError(e);
      setScreen({ kind: "error", title: m.title, body: m.body });
    }
  }, [code, userId]);

  useEffect(() => {
    setScreen({ kind: "loading" });
    void load();
  }, [load]);

  async function runAction(action: () => Promise<ReservationResponse>) {
    setActing(true);
    setNotice(null);
    const seq = ++reqSeqRef.current; // 진행 중이던 자동 재조회 응답을 무효화한다
    try {
      const r = await action();
      if (seq !== reqSeqRef.current) return;
      setScreen({ kind: "loaded", r });
      setLoadSeq((v) => v + 1);
    } catch (e) {
      if (seq !== reqSeqRef.current) return; // 더 새 요청이 이겼다 — 이 실패 표시도 버린다
      if (e instanceof ApiError && e.code === ERROR_CODES.INVALID_STATE_TRANSITION) {
        // 화면이 알던 상태가 낡았다 — 서버의 현재 상태를 다시 받아 그리되,
        // 충돌이 있었다는 사실은 배너로 남긴다 (조용히 바꾸지 않는다)
        await load();
        const m = messageFor(ERROR_CODES.INVALID_STATE_TRANSITION);
        setNotice(`${m.title} — ${m.body}`);
      } else {
        const m = messageForError(e);
        setScreen({ kind: "error", title: m.title, body: m.body });
      }
    } finally {
      setActing(false);
      setConfirmingCancel(false);
    }
  }

  if (screen.kind === "loading") {
    return (
      <div className="stack" role="status" aria-label="불러오는 중">
        <div className="card card-pad">
          <div className="skel" style={{ width: 180, height: 18, marginBottom: 8 }} />
          <div className="skel" style={{ width: 280, height: 12 }} />
        </div>
      </div>
    );
  }

  if (screen.kind === "not-found") {
    return (
      <div className="card">
        <div className="empty">
          <div className="big">예약을 찾을 수 없습니다</div>
          <p className="why">
            확인번호를 다시 확인해 주세요. 예약할 때 쓴 사용자 식별값(상단)이 다르면 같은
            번호라도 조회되지 않습니다.
          </p>
          <div className="actions">
            <button className="btn sm" onClick={() => router.push("/reservations")}>
              번호 다시 입력
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (screen.kind === "error") {
    return (
      <div className="card">
        <div className="empty">
          <div className="big">{screen.title}</div>
          <p className="why">{screen.body}</p>
          <div className="actions">
            <button className="btn sm" onClick={() => void load()}>다시 불러오기</button>
          </div>
        </div>
      </div>
    );
  }

  const { r } = screen;
  const view = viewOf(r);

  // 재예약은 이 예약의 소속 호텔로 — 응답에 hotelId가 없어 roomTypeId(시드)로 유도한다
  // (리뷰 라운드1 중요-1). 유도 불가면 hotelId를 빼고 검색 기본값에 맡긴다.
  const rebookHotelId = hotelIdOfRoomType(r.roomTypeId);
  // 날짜 처리 (라운드2 중요): 검색은 과거 checkIn을 400으로 막으므로, 지난 날짜를 그대로
  // 실으면 "같은 조건으로 다시 예약"이 오류 화면으로 끝난다 — clampStayFrom으로 보정.
  // 날짜 탑재 여부는 문구 비교가 아니라 매핑 표의 rebookWithDates가 결정한다 (라운드3).
  const clamped =
    view.rebookWithDates && r.checkIn && r.checkOut
      ? clampStayFrom(todayLocal(), r.checkIn, r.checkOut)
      : null;
  const rebookQuery = new URLSearchParams({
    ...(rebookHotelId !== undefined ? { hotelId: String(rebookHotelId) } : {}),
    ...(clamped ?? {}),
    guestCount: String(r.guestCount ?? 2),
    roomCount: String(r.roomCount ?? 1),
  });

  return (
    <>
      {notice && (
        <div
          className="card card-pad"
          role="alert"
          style={{ marginBottom: 14, borderColor: "var(--info)", background: "var(--info-tint)" }}
        >
          <div style={{ fontSize: 13.5, color: "var(--info)" }}>{notice}</div>
        </div>
      )}
      <div className="card card-pad" style={{ marginBottom: 14 }}>
        <div className="between" style={{ alignItems: "flex-start" }}>
          <div>
            <div className="inline" style={{ gap: 8, marginBottom: 4 }}>
              <span className={`badge ${view.tone}`}>{view.badgeLabel}</span>
              <span className="mono tnum" style={{ fontSize: 12.5, color: "var(--ink-faint)" }}>
                {r.confirmationCode}
              </span>
            </div>
            <div style={{ fontSize: 16.5, fontWeight: 700 }}>{view.title}</div>
            <div style={{ fontSize: 13, color: "var(--ink-soft)" }}>{view.description}</div>
          </div>
          {view.showCountdown && r.expiresAt && (
            // key로 재조회마다 재시작 — 0 도달 재조회 후 서버가 여전히 PENDING이면
            // 새 응답 기준으로 남은 시간을 다시 계산한다 (00:00 영구 정지 방지)
            <Countdown
              key={`${r.expiresAt}-${loadSeq}`}
              expiresAt={r.expiresAt}
              onExpired={() => void load()}
            />
          )}
        </div>
      </div>

      <div className="two-col">
        <div className="card card-pad">
          <p className="label">예약 내용</p>
          {r.checkIn && r.checkOut && (
            <div className="row">
              <span>일정</span>
              <b className="tnum">
                {r.checkIn} → {r.checkOut}{r.nights ? ` · ${r.nights}박` : ""}
              </b>
            </div>
          )}
          {r.roomCount !== undefined && r.guestCount !== undefined && (
            <div className="row">
              <span>객실·인원</span>
              <b className="tnum">{r.roomCount}실 · {r.guestCount}명</b>
            </div>
          )}
          {r.totalPrice !== undefined && (
            <div className="row">
              <span>금액</span>
              <b className="tnum">
                {won(r.totalPrice)}원{r.pricePerNight ? ` (1박 ${won(r.pricePerNight)}원)` : ""}
              </b>
            </div>
          )}
          {r.confirmedAt && (
            <div className="row"><span>결제 완료</span><b className="tnum">{r.confirmedAt.replace("T", " ")}</b></div>
          )}
          {r.terminatedAt && (
            <div className="row"><span>종료 시각</span><b className="tnum">{r.terminatedAt.replace("T", " ")}</b></div>
          )}
        </div>

        <div className="card card-pad" style={{ alignSelf: "start" }}>
          <p className="label">지금 할 수 있는 것</p>
          {view.actions.length === 0 && (
            <p className="note"><span>·</span><span>이 상태에서 화면으로 할 수 있는 동작은 없습니다.</span></p>
          )}
          <div className="stack" style={{ gap: 8 }}>
            {view.actions.includes("confirm") && (
              <button
                className="btn brass"
                disabled={acting}
                onClick={() => void runAction(() => api.confirmReservation(code, userId))}
              >
                {acting ? "처리 중…" : `${won(r.totalPrice)}원 결제하기`}
              </button>
            )}
            {view.actions.includes("cancel") &&
              (confirmingCancel ? (
                <button
                  className="btn"
                  style={{ background: "var(--danger)" }}
                  disabled={acting}
                  onClick={() => void runAction(() => api.cancelReservation(code, userId))}
                >
                  정말 취소합니다
                </button>
              ) : (
                <button
                  className="btn ghost"
                  disabled={acting}
                  onClick={() => {
                    // 브라우저 confirm 대신 버튼 2단 — 3초 안에 한 번 더 (시안 S3 상태 4)
                    setConfirmingCancel(true);
                    window.setTimeout(() => setConfirmingCancel(false), 3000);
                  }}
                >
                  예약 취소
                </button>
              ))}
            {view.actions.includes("rebook") && (
              <button className="btn" onClick={() => router.push(`/search?${rebookQuery}`)}>
                {view.rebookLabel ?? "다시 예약"}
              </button>
            )}
          </div>
          {view.actions.includes("confirm") && (
            <p className="note" style={{ marginTop: 11 }}>
              <span>ⓘ</span>
              <span>
                이 과제의 결제는 <b>내부 모의 결제</b>입니다. 승인·거절 결과 처리를 시연하기
                위한 것으로, 실제 결제가 일어나지 않습니다.
              </span>
            </p>
          )}
          {r.status === "CONFIRMED" && (
            <p className="note" style={{ marginTop: 11 }}>
              <span>ⓘ</span>
              <span>
                확정된 예약을 취소하면 <b>결제도 함께 취소</b>되고 방은 다시 판매됩니다.
              </span>
            </p>
          )}
        </div>
      </div>

      {r.roomTypeId !== undefined && (
        // 투숙 리뷰 (더미 API) — 작성은 숙박 완료(CHECKED_OUT)에서만: 서버가 준 상태로 게이트
        <div style={{ marginTop: 18 }}>
          <ReviewSection
            roomTypeId={r.roomTypeId}
            canWrite={r.status === "CHECKED_OUT"}
            userId={userId}
          />
        </div>
      )}
    </>
  );
}

function Countdown({ expiresAt, onExpired }: { expiresAt: string; onExpired: () => void }) {
  // 응답을 받은 순간을 기준으로 남은 시간을 만들고, 이후에는 1초씩 줄인다.
  const initial = useRef(computeRemainingSeconds(expiresAt, Date.now()));
  const [left, setLeft] = useState(initial.current);
  const firedRef = useRef(false);
  // onExpired를 ref로 들어 effect 의존성에서 뺀다 — 인라인 콜백이 재렌더마다 바뀌어
  // effect가 재실행되면, 발화 대기 중인 타이머가 유실된다 (라운드3 concurrency 중요).
  const onExpiredRef = useRef(onExpired);
  onExpiredRef.current = onExpired;

  useEffect(() => {
    if (left === null || firedRef.current) return;
    if (left <= 0) {
      // 0이 됐다고 화면이 만료 처리하지 않는다 — 서버에 다시 물어본다.
      // 0으로 마운트된 반복 재조회는 1초 지연(폴링 상한 1req/s), 자연 도달은 즉시.
      // firedRef는 실제 발화 시점에만 세운다 — 예약만 하고 세우면 StrictMode/재렌더의
      // 클린업 한 번에 발화가 영영 사라진다.
      const fire = () => {
        if (firedRef.current) return;
        firedRef.current = true;
        onExpiredRef.current();
      };
      const delay = expiryFireDelayMs(initial.current);
      if (delay > 0) {
        const t = window.setTimeout(fire, delay);
        return () => window.clearTimeout(t);
      }
      fire();
      return;
    }
    const t = window.setTimeout(() => setLeft((v) => (v === null ? v : v - 1)), 1000);
    return () => window.clearTimeout(t);
  }, [left]);

  if (left === null) return null;
  const hot = left <= 60;
  return (
    <div style={{ textAlign: "right" }}>
      <p className="label" style={{ marginBottom: 2 }}>결제까지 남은 시간</p>
      <div
        className="mono tnum"
        style={{ fontSize: 40, fontWeight: 600, lineHeight: 1, color: hot ? "var(--danger)" : "var(--ink)" }}
      >
        {formatMmSs(left)}
      </div>
    </div>
  );
}
