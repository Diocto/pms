// 결제 유예 카운트다운 계산.
//
// 서버 응답에는 "지금 몇 시인지"가 없다 ([가정] 대장 참조). 그래서 응답을 받은 순간의
// 브라우저 시각과 expiresAt의 차이로 시작값을 만들고, 이후에는 경과 시간만 센다.
// 브라우저 시계가 틀리면 표시도 틀릴 수 있지만, 만료 판정은 어차피 서버 몫이다 —
// 0이 되면 화면은 스스로 만료 처리하지 않고 다시 조회한다 (시안 S3 상태 1).

const OFFSET_RE = /[+-]\d{2}:\d{2}$|Z$/;

export function computeRemainingSeconds(expiresAt: string, nowMs: number): number | null {
  // 오프셋 없는 로컬 시각은 서버 타임존(Asia/Seoul)으로 해석한다
  const normalized = OFFSET_RE.test(expiresAt) ? expiresAt : `${expiresAt}+09:00`;
  const t = Date.parse(normalized);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((t - nowMs) / 1000));
}

// 0 도달 시 재조회를 언제 발화할지의 판정 — 컴포넌트 밖에 두어 테스트 가능하게 한다.
// 0으로 "마운트된" 경우(재조회 후에도 서버가 PENDING)는 1초 지연을 강제해 최악에도
// 1req/s 상한을 만들고, 자연 카운트다운으로 0에 도달한 첫 회는 즉시 발화한다.
export function expiryFireDelayMs(initialRemaining: number | null): number {
  return initialRemaining !== null && initialRemaining <= 0 ? 1000 : 0;
}

export function formatMmSs(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
