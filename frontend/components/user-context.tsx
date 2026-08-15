"use client";

// X-User-Id 값을 화면 전체에 공유한다. localStorage에 보관해 화면 이동·새로고침에도
// 유지한다 — "같은 예약을 다루는 요청은 같은 값"이라는 계약 때문에 유지가 중요하다.
// 상태 관리 라이브러리는 쓰지 않는다(시안 D4). React 내장 Context로 충분하다.

import { createContext, useContext, useEffect, useState } from "react";
import { DEFAULT_USER_ID, normalizeUserId } from "@/lib/user-id";

const STORAGE_KEY = "pms.userId";

const UserIdContext = createContext<{
  userId: string;
  setUserId: (v: string) => void;
}>({ userId: DEFAULT_USER_ID, setUserId: () => {} });

export function UserIdProvider({ children }: { children: React.ReactNode }) {
  // 첫 렌더는 서버·클라이언트 모두 기본값으로 그린다. localStorage는 브라우저에만
  // 있으므로 마운트 후에 읽는다 — 서버가 그린 HTML과 첫 클라이언트 렌더가 달라지면
  // 하이드레이션 불일치 오류가 난다. (교육 노트 2의 소재)
  const [userId, setUserIdState] = useState(DEFAULT_USER_ID);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved !== null) setUserIdState(normalizeUserId(saved));
  }, []);

  const setUserId = (v: string) => {
    const normalized = normalizeUserId(v);
    setUserIdState(normalized);
    window.localStorage.setItem(STORAGE_KEY, normalized);
  };

  return (
    <UserIdContext.Provider value={{ userId, setUserId }}>
      {children}
    </UserIdContext.Provider>
  );
}

export function useUserId() {
  return useContext(UserIdContext);
}
