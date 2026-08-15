"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useUserId } from "./user-context";

// 시드에 있는 사용자 예시 + 직접 입력. 그럴듯한 로그인 화면을 만들지 않는다(브리핑) —
// 없는 기능(인증)을 있는 것처럼 보이게 하지 않기 위한 표기다.
const PRESETS = ["user-1001", "user-1002", "user-1003"];

export function TopNav() {
  const pathname = usePathname();
  const { userId, setUserId } = useUserId();
  const [editing, setEditing] = useState(false);
  const isPreset = PRESETS.includes(userId);

  return (
    <header className="nav">
      <Link href="/search" className="nav-mark">
        <span className="ko">여정</span>
        <span className="en">PMS demo</span>
      </Link>
      <nav className="nav-links">
        <Link href="/search" className={pathname.startsWith("/search") || pathname.startsWith("/book") ? "on" : ""}>
          객실 검색
        </Link>
        <Link href="/reservations" className={pathname.startsWith("/reservations") ? "on" : ""}>
          예약 확인
        </Link>
      </nav>
      <div className="nav-user">
        <span>사용자(과제용 식별값)</span>
        {editing || !isPreset ? (
          <input
            aria-label="X-User-Id 직접 입력"
            defaultValue={userId}
            maxLength={64}
            onBlur={(e) => {
              setUserId(e.target.value);
              setEditing(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
        ) : (
          <select
            aria-label="X-User-Id 선택"
            value={userId}
            onChange={(e) => {
              if (e.target.value === "__custom__") setEditing(true);
              else setUserId(e.target.value);
            }}
          >
            {PRESETS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
            <option value="__custom__">직접 입력…</option>
          </select>
        )}
      </div>
    </header>
  );
}
