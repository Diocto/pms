"use client";

// 랜딩 A안 「검색이 주인공」 — 관리자 확정 (2026-08-16, 랜딩-UX-조사 §4).
// ① 세리프 헤드라인 + 중앙 대형 검색폼 (3조작: 체크인 → 체크아웃 → 검색)
// ② 평점 좋은 숙소 (실데이터 — 더미 리뷰 평균, "평점순" 명시 + 오늘 실재고 배지)
// ③ 신뢰 밴드 (취소 정책 · 데모 안내) ④ 푸터
// 금지: 지어낸 긴급성·취소선 정가·회원 전용가·최저가 보장 — 전부 쓰지 않는다.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/backend";
import { addDays, todayLocal } from "@/lib/dates";
import { validateSearchForm, type SearchFormErrors } from "@/lib/search-form";

function won(n: number): string {
  return n.toLocaleString("ko-KR");
}

const CARD_PALETTES = [
  ["#2E4A3A", "#7A8F6B", "#C9BD9A"],
  ["#1F3B2C", "#4E6B50", "#A9B594"],
  ["#33566B", "#6B93A9", "#CFE0E6"],
] as const;

interface TopStay {
  hotelId: number;
  hotelName: string;
  roomTypeId: number;
  roomTypeName: string;
  basePrice: number;
  avg: number;
  count: number;
  todayRemaining: number | null; // 오늘 1박 실재고 (없으면 미표기)
}

export default function Landing() {
  const router = useRouter();
  const today = todayLocal();
  const [checkIn, setCheckIn] = useState(today);
  const [checkOut, setCheckOut] = useState(addDays(today, 1));
  const [guestCount, setGuestCount] = useState(2);
  const [errors, setErrors] = useState<SearchFormErrors>({});
  const [top, setTop] = useState<TopStay[] | null>(null);

  // ② 평점 좋은 숙소 — 더미 리뷰가 있는 객실들의 실평균으로 상위 3곳
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const hotels = await api.fetchHotels();
        const candidates = hotels
          .slice(0, 2) // 리뷰 시드가 있는 기존 호텔 1·2의 객실들
          .flatMap((h) =>
            h.roomTypes.map((rt) => ({
              hotelId: h.hotelId,
              hotelName: h.name,
              roomTypeId: rt.roomTypeId,
              roomTypeName: rt.name,
              basePrice: rt.basePrice,
            })),
          );
        const rated = await Promise.all(
          candidates.map(async (c) => {
            const reviews = await api.listReviews(c.roomTypeId).catch(() => []);
            return reviews.length === 0
              ? null
              : {
                  ...c,
                  avg: reviews.reduce((s, r) => s + r.rating, 0) / reviews.length,
                  count: reviews.length,
                };
          }),
        );
        const top3 = rated
          .filter((c): c is Exclude<typeof c, null> => c !== null)
          .sort((a, b) => b.avg - a.avg || b.count - a.count)
          .slice(0, 3);
        // 오늘 1박 실재고 — 정직한 잔여 표시 (일별 재고 실제 값)
        const withStock = await Promise.all(
          top3.map(async (c) => {
            try {
              const avail = await api.searchAvailability({
                hotelId: c.hotelId,
                checkIn: today,
                checkOut: addDays(today, 1),
                guestCount: 2,
                roomCount: 1,
              });
              const item = avail.items.find((i) => i.roomTypeId === c.roomTypeId);
              return { ...c, todayRemaining: item ? item.minRemaining : 0 };
            } catch {
              return { ...c, todayRemaining: null };
            }
          }),
        );
        if (!cancelled) setTop(withStock);
      } catch {
        if (!cancelled) setTop([]); // 추천 실패는 랜딩을 막지 않는다
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [today]);

  function submit() {
    const v = { checkIn, checkOut, guestCount, roomCount: 1 };
    const nextErrors = validateSearchForm(v, today);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    const q = new URLSearchParams({
      checkIn,
      checkOut,
      guestCount: String(guestCount),
      roomCount: "1",
    });
    router.push(`/search?${q}`);
  }

  return (
    <>
      {/* ① 첫 화면 — 헤드라인 + 대형 검색폼 (리조트 무드 배경) */}
      <section
        style={{
          margin: "-30px -28px 0",
          padding: "84px 28px 64px",
          background:
            "linear-gradient(160deg, #1F3B2C 0%, #3E5C48 46%, #8FA184 78%, #E9E2CF 100%)",
          textAlign: "center",
        }}
      >
        <p
          style={{
            fontSize: 11.5,
            letterSpacing: "0.3em",
            textTransform: "uppercase",
            color: "#C9BD9A",
            fontWeight: 700,
            margin: "0 0 14px",
          }}
        >
          Yeojeong — Stay
        </p>
        <h1
          className="serif"
          style={{
            fontSize: "clamp(30px, 5vw, 46px)",
            fontWeight: 400,
            color: "#F5F1E6",
            letterSpacing: "0.01em",
            lineHeight: 1.35,
            margin: "0 0 8px",
            textWrap: "balance",
          }}
        >
          백 곳의 호텔, 단 하나의 밤을 위해
        </h1>
        <p style={{ color: "#D9D3C0", fontSize: 14.5, margin: "0 0 36px" }}>
          날짜를 고르면, 그 기간 내내 비어 있는 방만 정직하게 보여드립니다.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          style={{
            maxWidth: 760,
            margin: "0 auto",
            background: "var(--surface)",
            border: "1px solid var(--forest)",
            display: "grid",
            gridTemplateColumns: "1fr 1fr 0.6fr auto",
            textAlign: "left",
          }}
        >
          <div style={{ padding: "12px 18px", borderRight: "1px solid var(--line)" }}>
            <p className="label">체크인</p>
            <input
              type="date"
              className={`field mono tnum${errors.checkIn ? " bad" : ""}`}
              style={{ border: 0, padding: "2px 0" }}
              value={checkIn}
              onChange={(e) => setCheckIn(e.target.value)}
              aria-label="체크인"
            />
          </div>
          <div style={{ padding: "12px 18px", borderRight: "1px solid var(--line)" }}>
            <p className="label">체크아웃</p>
            <input
              type="date"
              className={`field mono tnum${errors.checkOut ? " bad" : ""}`}
              style={{ border: 0, padding: "2px 0" }}
              value={checkOut}
              onChange={(e) => setCheckOut(e.target.value)}
              aria-label="체크아웃"
            />
          </div>
          <div style={{ padding: "12px 18px" }}>
            <p className="label">인원</p>
            <input
              type="number"
              min={1}
              max={20}
              className={`field tnum${errors.guestCount ? " bad" : ""}`}
              style={{ border: 0, padding: "2px 0" }}
              value={guestCount}
              onChange={(e) => setGuestCount(Number(e.target.value))}
              aria-label="인원"
            />
          </div>
          <button className="btn brass" type="submit" style={{ borderRadius: 0 }}>
            검색
          </button>
        </form>
        {Object.values(errors).filter(Boolean).map((msg) => (
          <div key={msg} style={{ color: "#F2D6C9", fontSize: 12.5, marginTop: 8 }}>{msg}</div>
        ))}
      </section>

      {/* ② 평점 좋은 숙소 — 실데이터, 기준 명시 */}
      <section style={{ padding: "44px 0 8px" }}>
        <div className="between" style={{ marginBottom: 14 }}>
          <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, margin: 0 }}>
            평점 좋은 숙소
          </h2>
          <span className="note">투숙 리뷰 평점순 · 잔여는 오늘 1박 실제 값</span>
        </div>

        {top === null && (
          <div className="stack" role="status" aria-label="추천 불러오는 중">
            <div className="card card-pad"><div className="skel" style={{ width: 260, height: 14 }} /></div>
          </div>
        )}

        {top !== null && top.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
            {top.map((c, i) => {
              const [a, b, cc] = CARD_PALETTES[i % CARD_PALETTES.length];
              return (
                <div className="card" key={c.roomTypeId}>
                  <div
                    className="ph"
                    style={{
                      width: "100%",
                      height: 120,
                      border: 0,
                      borderBottom: "1px solid var(--line)",
                      background: `linear-gradient(135deg, ${a}, ${b} 55%, ${cc})`,
                    }}
                    aria-hidden="true"
                  >
                    <i>{c.roomTypeName}</i>
                  </div>
                  <div className="card-pad" style={{ paddingTop: 14 }}>
                    <b className="serif" style={{ fontSize: 16.5 }}>{c.roomTypeName}</b>
                    <div className="note" style={{ display: "block" }}>{c.hotelName}</div>
                    <div style={{ margin: "6px 0 2px" }}>
                      <span className="stars">{"★".repeat(Math.round(c.avg))}</span>{" "}
                      <b className="tnum" style={{ fontSize: 13 }}>{c.avg.toFixed(1)}</b>
                      <span className="note" style={{ display: "inline" }}> · 리뷰 {c.count}건</span>
                    </div>
                    <div className="between" style={{ marginTop: 8 }}>
                      <span className="tnum" style={{ fontSize: 13.5 }}>
                        1박 <b>{won(c.basePrice)}원</b>
                      </span>
                      {c.todayRemaining !== null && c.todayRemaining > 0 && c.todayRemaining <= 5 && (
                        <span className="badge warn tnum">오늘 {c.todayRemaining}실 남음</span>
                      )}
                      {c.todayRemaining !== null && c.todayRemaining === 0 && (
                        <span className="badge mute">오늘 매진</span>
                      )}
                    </div>
                    <button
                      className="btn ghost sm"
                      style={{ width: "100%", marginTop: 12 }}
                      onClick={() => {
                        const q = new URLSearchParams({
                          checkIn,
                          checkOut,
                          guestCount: String(guestCount),
                          roomCount: "1",
                          hotelId: String(c.hotelId),
                        });
                        router.push(`/search?${q}`);
                      }}
                    >
                      이 호텔 잔여 보기
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ③ 신뢰 밴드 — 사실만 말한다 */}
      <section
        className="card"
        style={{ margin: "36px 0 0", padding: "20px 26px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 18 }}
      >
        <div>
          <p className="label">취소 정책</p>
          <p style={{ fontSize: 13.5, color: "var(--ink-soft)", margin: 0 }}>
            체크인 전이면 언제든 무료로 취소할 수 있고, 취소된 방은 즉시 다시 판매됩니다.
            결제 후 취소하면 결제도 함께 취소됩니다.
          </p>
        </div>
        <div>
          <p className="label">10분 결제 유예</p>
          <p style={{ fontSize: 13.5, color: "var(--ink-soft)", margin: 0 }}>
            예약하면 방이 10분간 확보됩니다. 여러 번 눌러도 예약은 한 건만 만들어집니다.
          </p>
        </div>
        <div>
          <p className="label">데모 안내</p>
          <p style={{ fontSize: 13.5, color: "var(--ink-soft)", margin: 0 }}>
            상단의 사용자 전환은 <b>로그인이 아니며</b>(ADR-0006), 결제는 내부 모의 결제입니다.
            동시성·멱등성 과제의 시연용 서비스입니다.
          </p>
        </div>
      </section>

      {/* ④ 푸터 */}
      <footer style={{ padding: "30px 0 8px", textAlign: "center" }}>
        <span className="serif" style={{ letterSpacing: "0.3em", color: "var(--forest)" }}>여 정</span>
        <p className="note" style={{ justifyContent: "center", marginTop: 6 }}>
          <span>PMS 숙박 예약 과제 데모 · 호텔 100곳 · 판매 기간 2026-08-01 ~ 10-29</span>
        </p>
      </footer>
    </>
  );
}
