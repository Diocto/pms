import type { Metadata } from "next";
import { TopNav } from "@/components/top-nav";
import { UserIdProvider } from "@/components/user-context";
import "./globals.css";

// 서버 컴포넌트 — 뼈대(문서 구조·정적 부분)만 서버에서 그린다.
// 상호작용이 본질인 세 화면의 본체는 클라이언트 컴포넌트다 (시안 D5).

export const metadata: Metadata = {
  title: "여정 — PMS 예약 데모",
  description: "숙박 예약 시스템 과제의 시연용 화면",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <UserIdProvider>
          <TopNav />
          <main className="main">{children}</main>
        </UserIdProvider>
      </body>
    </html>
  );
}
