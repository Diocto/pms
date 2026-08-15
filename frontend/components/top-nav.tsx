"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { createSavedUserIds } from "@/lib/saved-user-ids";
import { useUserId } from "./user-context";

// 시드에 있는 사용자 예시 + 직접 입력. 그럴듯한 로그인 화면을 만들지 않는다(브리핑) —
// 없는 기능(인증)을 있는 것처럼 보이게 하지 않기 위한 표기다.
// 직접 입력한 값은 저장해 셀렉트에 다시 보여준다 (범위 내 "가입" 대체 — ADR-0006).
const PRESETS = ["user-1001", "user-1002", "user-1003"];

export function TopNav() {
  const pathname = usePathname();
  const { userId, setUserId } = useUserId();
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState<string[]>([]);

  // localStorage는 마운트 후에 읽는다 — 하이드레이션 불일치 방지 (교육 노트 2)
  useEffect(() => {
    setSaved(createSavedUserIds(window.localStorage, PRESETS).list());
  }, []);

  const known = PRESETS.includes(userId) || saved.includes(userId);

  function commitCustom(value: string) {
    const store = createSavedUserIds(window.localStorage, PRESETS);
    setUserId(value);
    if (value.trim()) {
      store.save(value.trim());
      setSaved(store.list());
    }
    setEditing(false);
  }

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
      <div
        className="nav-user"
        title="이 값이 X-User-Id 헤더로 나갑니다. 누구나 아무 값이나 고를 수 있으므로 인증이 아니며, 로그인·회원가입은 이 과제의 범위 밖입니다 (ADR-0006)."
      >
        <span>
          사용자 전환{" "}
          <span style={{ color: "var(--ink-faint)" }}>· 로그인 아님</span>
        </span>
        {editing || !known ? (
          <input
            aria-label="X-User-Id 직접 입력"
            defaultValue={userId}
            maxLength={64}
            autoFocus={editing}
            onBlur={(e) => commitCustom(e.target.value)}
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
            {saved.length > 0 && (
              <optgroup label="내가 만든 식별값">
                {saved.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </optgroup>
            )}
            <option value="__custom__">새 식별값 만들기…</option>
          </select>
        )}
      </div>
    </header>
  );
}
