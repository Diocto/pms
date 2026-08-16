import { redirect } from "next/navigation";

// 첫 화면은 검색이다. (히어로 랜딩은 2026-08-16 관리자 지시로 제거 — 보고서 D9 개정)
export default function Home() {
  redirect("/search");
}
