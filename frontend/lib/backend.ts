// 화면이 쓰는 api 인스턴스는 여기서 하나만 만든다.
//
// NEXT_PUBLIC_API_MODE 세 값 (번들에 실리는 모드 플래그 — 비밀값 아님):
//   mock    전부 가짜 백엔드 (F01·F03 없이 화면 개발·시연)
//   hybrid  검색(/api/availability)만 가짜, 예약 관련은 실 백엔드
//           — F01은 병합됐지만 F03 검색 API가 아직 없는 구간용 (T6 1단계)
//           주의: 검색의 잔여 수량은 가짜라 실 예약을 반영하지 않는다. F03 병합 시 real로
//   real    전부 실 백엔드 (기본값)
//
// 실 호출은 same-origin /api/* 로 나가고 next.config.mjs 의 rewrites가
// 백엔드(FastAPI, 기본 http://localhost:8000)로 프록시한다.

import { createApi, type Api } from "./api";
import { createMockBackend } from "./mock-backend";

const mode = process.env.NEXT_PUBLIC_API_MODE ?? "real";
export const isMockMode = mode === "mock";
export const isHybridMode = mode === "hybrid";

function buildFetch(): typeof fetch | undefined {
  if (mode === "mock") return createMockBackend({ latencyMs: 250 }).fetchLike;
  // 투숙 리뷰는 실 백엔드에 없는 더미 API다 (관리자: "더미 API로 붙여서") —
  // real 모드에서도 /api/reviews만 가짜 백엔드로 라우팅한다.
  const dummy = createMockBackend({ latencyMs: 150 }).fetchLike;
  if (mode === "hybrid") {
    return (input, init) => {
      const url = String(input);
      return url.includes("/api/availability") || url.includes("/api/reviews")
        ? dummy(input, init)
        : fetch(input, init);
    };
  }
  return (input, init) =>
    String(input).includes("/api/reviews") ? dummy(input, init) : fetch(input, init);
}

const fetchLike = buildFetch();
export const api: Api = createApi(fetchLike ? { fetchLike } : {});
