// 에러 코드 → 화면 문구. 매핑은 이 파일 한 곳뿐이다.
// 진실: docs/design/F05-화면-시안.html 「응답 → 문구 매핑」 표.
//
// 원칙 (시안 S10 계열에서 확정):
// - 사용자가 잘못한 게 없으면 사과체를 쓰지 않는다. 사실 · 현재 상태 · 다음 행동만.
// - 돈이 걸린 화면에는 "결제는 진행되지 않았습니다"를 반드시 넣는다.
// - 내부 정보는 traceId만, "문의 번호"라는 이름으로 노출한다.

export interface ScreenMessage {
  title: string;
  body: string;
}

const MESSAGES: Record<string, ScreenMessage> = {
  INVALID_REQUEST: {
    title: "입력을 확인해 주세요",
    body: "요청한 조건이 규칙에 맞지 않습니다. 날짜·인원·객실 수를 확인해 주세요.",
  },
  RESOURCE_NOT_FOUND: {
    title: "예약을 찾을 수 없습니다",
    body: "확인번호를 다시 확인해 주세요. 예약할 때 쓴 사용자 식별값이 다르면 같은 번호라도 조회되지 않습니다.",
  },
  INVALID_STATE_TRANSITION: {
    title: "예약 상태가 바뀌었습니다",
    body: "화면에 보이던 상태와 지금 상태가 다릅니다. 최신 상태를 다시 확인합니다.",
  },
  INSUFFICIENT_INVENTORY: {
    title: "방금 마감되었습니다",
    body: "방금 다른 분이 먼저 예약했습니다. 결제는 진행되지 않았습니다.",
  },
  REQUEST_IN_PROGRESS: {
    title: "예약을 처리하고 있습니다",
    body: "조금 전 요청이 처리 중입니다. 잠시 후 결과를 확인합니다. 중복으로 잡히지 않습니다.",
  },
  LOCK_ACQUISITION_FAILED: {
    title: "지금 예약이 몰리고 있습니다",
    body: "잠시 후 다시 시도해 주세요. 입력한 내용은 그대로 남아 있습니다.",
  },
  INTERNAL_ERROR: {
    title: "처리하지 못했습니다",
    body: "일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
  },
};

const FALLBACK: ScreenMessage = {
  title: "처리하지 못했습니다",
  body: "알 수 없는 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
};

export function messageFor(code: string, traceId?: string): ScreenMessage {
  const base = MESSAGES[code] ?? FALLBACK;
  if (!traceId) return base;
  return { ...base, body: `${base.body} (문의 번호 ${traceId})` };
}
