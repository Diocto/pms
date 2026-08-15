// 화면이 쓰는 api 인스턴스는 여기서 하나만 만든다.
//
// NEXT_PUBLIC_API_MODE=mock 이면 가짜 백엔드(mock-backend.ts)로 붙는다.
// NEXT_PUBLIC_ 값은 번들에 실려 브라우저에서 전부 보인다 — 모드 스위치라 문제없지만,
// 이 접두어에 비밀값을 담으면 안 된다는 사실을 여기 적어 둔다.
//
// 실제 모드에서는 same-origin /api/* 로 나가고, next.config.mjs 의 rewrites가
// 백엔드(FastAPI)로 프록시한다. T6에서 이 경로로 왕복을 확인한다.

import { createApi, type Api } from "./api";
import { createMockBackend } from "./mock-backend";

export const isMockMode = process.env.NEXT_PUBLIC_API_MODE === "mock";

export const api: Api = isMockMode
  ? createApi({ fetchLike: createMockBackend({ latencyMs: 250 }).fetchLike })
  : createApi();
