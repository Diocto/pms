import { redirect } from "next/navigation";

// 첫 화면은 검색이다 (시안 S1).
export default function Home() {
  redirect("/search");
}
