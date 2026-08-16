import Link from "next/link";

// 히어로(랜딩) — 서비스 소개와 검색 진입 (관리자 지시 2026-08-16).
// 정적 소개뿐이라 서버 컴포넌트다 (시안 D5: 상호작용 없는 부분은 서버에서 그린다).
// 소개 문구는 전부 실제 동작에서 나온 사실이다 — 없는 기능을 있는 것처럼 쓰지 않는다.

export default function Home() {
  return (
    <div className="stack" style={{ gap: 28, paddingTop: 24 }}>
      <section style={{ maxWidth: "56ch" }}>
        <p
          style={{
            fontSize: 12,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--brass)",
            fontWeight: 700,
            margin: "0 0 10px",
          }}
        >
          여정 — 숙박 예약
        </p>
        <h1
          style={{
            fontSize: 34,
            lineHeight: 1.25,
            letterSpacing: "-0.02em",
            margin: "0 0 12px",
            textWrap: "balance",
          }}
        >
          머무를 밤을, 남은 방 그대로
        </h1>
        <p style={{ fontSize: 15.5, lineHeight: 1.7, color: "var(--ink-soft)", margin: "0 0 20px" }}>
          서울 그랜드 호텔과 부산 오션뷰 호텔의 잔여 객실을 날짜 단위로 확인하고,
          방을 10분간 잡아 둔 뒤 결제해 확정하는 예약 서비스입니다. 확정된 예약은
          언제든 취소할 수 있고, 취소된 방은 바로 다시 판매됩니다.
        </p>
        <div className="inline">
          <Link href="/search" className="btn brass" style={{ textDecoration: "none" }}>
            객실 검색하기
          </Link>
          <Link href="/reservations" className="btn ghost" style={{ textDecoration: "none" }}>
            내 예약 보기
          </Link>
        </div>
      </section>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 14,
        }}
      >
        <div className="card card-pad">
          <p className="label">날짜 단위 잔여</p>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>하루라도 비면 팔지 않습니다</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-soft)", margin: 0 }}>
            재고를 날짜별로 세기 때문에, 기간 중 단 하루라도 방이 없으면 검색 결과에서
            빠집니다. 보이는 방은 전 기간 묵을 수 있는 방입니다.
          </p>
        </div>
        <div className="card card-pad">
          <p className="label">10분 결제 유예</p>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>예약하면 방이 잡힙니다</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-soft)", margin: 0 }}>
            예약 버튼을 누르는 순간 방이 10분간 확보됩니다. 시간 안에 결제하지 않으면
            자동으로 풀려 다른 손님에게 돌아갑니다.
          </p>
        </div>
        <div className="card card-pad">
          <p className="label">중복 없는 예약</p>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>여러 번 눌러도 한 건입니다</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-soft)", margin: 0 }}>
            네트워크가 끊겨 다시 시도해도, 버튼을 연달아 눌러도 같은 요청은 한 건의
            예약으로만 처리됩니다.
          </p>
        </div>
      </section>

      <p className="note">
        <span>ⓘ</span>
        <span>
          동시성·멱등성·상태 전이를 다루는 과제의 시연용 서비스입니다. 상단의 사용자
          전환은 <b>로그인이 아니며</b>, 결제는 내부 모의 결제입니다 (ADR-0006).
        </span>
      </p>
    </div>
  );
}
