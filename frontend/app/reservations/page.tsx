"use client";

// 예약 확인 진입 — 확인번호를 입력해 상세로 간다. 목록 화면은 없다(시안 D7:
// F01에 목록 API가 없고, 백엔드에 추가를 요구하지 않는다).

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function ReservationLookupPage() {
  const router = useRouter();
  const [code, setCode] = useState("");

  return (
    <>
      <h1 className="h1">예약 확인</h1>
      <p className="sub">예약할 때 받은 확인번호를 입력해 주세요.</p>
      <form
        className="card card-pad inline"
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
    </>
  );
}
