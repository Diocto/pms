// 사용자 식별값 규칙.
//
// 이 값이 그대로 X-User-Id 헤더로 나간다. 이 헤더는 클라이언트가 마음대로 정할 수
// 있으므로 **인증이 아니다** — 남이 예약할 때 쓴 값을 알면 그 예약을 조회·취소할 수
// 있다. 과제가 의도적으로 범위에서 뺀 것이며(ADR-0006), 여기서 고칠 문제가 아니다.
// 서버 쪽 완화는 하나: 소유자 불일치를 403이 아니라 404로 응답해 존재를 숨긴다.
//
// 계약(F01 스펙 1.9 (6)): VARCHAR(64), 비어 있지 않으면 어떤 값이든 받는다.

export const DEFAULT_USER_ID = "user-1001";

const MAX_LENGTH = 64;

export function normalizeUserId(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_LENGTH) return DEFAULT_USER_ID;
  return trimmed;
}
