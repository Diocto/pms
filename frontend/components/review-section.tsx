"use client";

// 투숙 리뷰 — 더미 API (관리자 컨펌 2026-08-16 "더미 API로 붙여서").
// 목록·평균은 누구나 보고, 작성 폼은 숙박 완료(CHECKED_OUT) 예약 화면에서만 열린다 —
// 게이트 근거는 서버가 준 예약 상태다. 새로고침하면 더미 저장분은 초기화된다(문서화).

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/backend";
import { messageForError } from "@/lib/error-messages";
import type { ReviewInfo } from "@/lib/contracts";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; reviews: ReviewInfo[] }
  | { kind: "error"; body: string };

export function ReviewSection({
  roomTypeId,
  canWrite,
  userId,
}: {
  roomTypeId: number;
  canWrite: boolean;
  userId: string;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(5);

  const load = useCallback(async () => {
    try {
      const reviews = await api.listReviews(roomTypeId);
      setState({ kind: "loaded", reviews });
    } catch (e) {
      setState({ kind: "error", body: messageForError(e).body });
    }
  }, [roomTypeId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit() {
    const trimmed = comment.trim();
    if (!trimmed) {
      setFormError("한 줄 후기를 적어 주세요.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await api.createReview({ roomTypeId, rating, comment: trimmed }, userId);
      setComment("");
      await load();
    } catch (e) {
      setFormError(messageForError(e).body);
    } finally {
      setSubmitting(false);
    }
  }

  const avg =
    state.kind === "loaded" && state.reviews.length > 0
      ? state.reviews.reduce((s, r) => s + r.rating, 0) / state.reviews.length
      : null;

  return (
    <div className="card card-pad">
      <div className="between" style={{ marginBottom: 8 }}>
        <div className="inline" style={{ gap: 12 }}>
          <p className="label" style={{ margin: 0 }}>투숙 리뷰</p>
          {avg !== null && (
            <span className="inline" style={{ gap: 6 }}>
              <span className="stars">{"★".repeat(Math.round(avg))}</span>
              <b className="tnum">{avg.toFixed(1)}</b>
              <span className="note">리뷰 {state.kind === "loaded" ? state.reviews.length : 0}건</span>
            </span>
          )}
        </div>
        <span className="note">체험 기능 — 더미 저장 (서버 재시작 시 초기화)</span>
      </div>

      {state.kind === "loading" && <div className="skel" style={{ width: 240, height: 13 }} />}
      {state.kind === "error" && <p className="note"><span>·</span><span>{state.body}</span></p>}

      {state.kind === "loaded" && state.reviews.length === 0 && (
        <p className="note"><span>·</span><span>아직 리뷰가 없습니다. 첫 후기를 남겨 보세요.</span></p>
      )}

      {state.kind === "loaded" &&
        state.reviews.slice(0, visibleCount).map((rv) => (
          <div key={rv.reviewId} style={{ padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
            <div className="serif" style={{ fontSize: 15.5, lineHeight: 1.6 }}>
              “{rv.comment}”
            </div>
            <div className="note" style={{ marginTop: 3 }}>
              <span className="stars">{"★".repeat(rv.rating)}</span>
              <span>{rv.userId} · {rv.createdAt.slice(0, 10)}</span>
            </div>
          </div>
        ))}

      {state.kind === "loaded" && state.reviews.length > visibleCount && (
        <button
          className="btn ghost sm"
          style={{ marginTop: 10 }}
          onClick={() => setVisibleCount((v) => v + 5)}
        >
          리뷰 더보기 ({state.reviews.length - visibleCount}건 남음)
        </button>
      )}

      {canWrite ? (
        <div style={{ marginTop: 14 }}>
          <p className="label">숙박을 마치셨네요 — 후기를 남겨 주세요</p>
          <div className="inline" style={{ alignItems: "stretch" }}>
            <select
              className="field"
              style={{ width: 110 }}
              value={rating}
              onChange={(e) => setRating(Number(e.target.value))}
              aria-label="별점"
            >
              {[5, 4, 3, 2, 1].map((n) => (
                <option key={n} value={n}>{"★".repeat(n)} {n}점</option>
              ))}
            </select>
            <input
              className="field grow"
              placeholder="한 줄 후기"
              value={comment}
              maxLength={120}
              onChange={(e) => setComment(e.target.value)}
              aria-label="후기"
            />
            <button className="btn brass sm" disabled={submitting} onClick={() => void submit()}>
              {submitting ? "등록 중…" : "등록"}
            </button>
          </div>
          {formError && <div className="field-error">{formError}</div>}
        </div>
      ) : (
        <p className="note" style={{ marginTop: 12 }}>
          <span>ⓘ</span>
          <span>리뷰 작성은 <b>숙박을 완료한 예약</b>에서만 열립니다.</span>
        </p>
      )}
    </div>
  );
}
