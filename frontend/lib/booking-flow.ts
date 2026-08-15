// 409의 4단계 흐름 — 시안 S2 상태 3, 브리핑 권장 흐름 그대로.
//
// 검색 결과는 캐시 때문에 최대 10초 낡을 수 있어, "예약 가능"으로 보이는데 누르면
// 409가 나는 일이 설계상 정상으로 일어난다. 그래서 이 흐름은 오류 처리가 아니라
// 본편이다: 사실을 알리고 → fresh로 재확인하고 → 남아 있으면 같은 키로 다시 → 최대
// 2회에서 멈춘다. 없는 재고에 계속 부딪히는 건 사용자에게도 서버에도 손해다.
//
// create는 호출자가 같은 멱등성 키로 고정해 넘긴다 — 재시도가 다른 키로 나가면
// 멱등성이 무의미해진다.

import { ApiError } from "./api";
import { ERROR_CODES, type ReservationResponse } from "./contracts";

const MAX_AUTO_RETRIES = 2;

export type BookingPhase =
  | { kind: "submitting" }
  | { kind: "sold-just-now"; attempt: number }
  | { kind: "checking-fresh"; attempt: number }
  | { kind: "retrying"; attempt: number };

export type BookingOutcome =
  | { kind: "created"; reservation: ReservationResponse }
  | { kind: "sold-out" };

export interface BookingFlowDeps {
  /** 같은 멱등성 키로 고정된 예약 생성 호출 */
  create: () => Promise<ReservationResponse>;
  /** fresh=true 재검색 후 "아직 예약 가능한가"만 답한다 */
  checkFresh: () => Promise<boolean>;
  onPhase: (phase: BookingPhase) => void;
}

export async function attemptBooking(deps: BookingFlowDeps): Promise<BookingOutcome> {
  deps.onPhase({ kind: "submitting" });

  for (let attempt = 0; ; attempt += 1) {
    try {
      const reservation = await deps.create();
      return { kind: "created", reservation };
    } catch (e) {
      const isInventory409 =
        e instanceof ApiError && e.code === ERROR_CODES.INSUFFICIENT_INVENTORY;
      if (!isInventory409) throw e; // 다른 실패는 이 흐름의 일이 아니다

      if (attempt >= MAX_AUTO_RETRIES) return { kind: "sold-out" };

      deps.onPhase({ kind: "sold-just-now", attempt: attempt + 1 });
      deps.onPhase({ kind: "checking-fresh", attempt: attempt + 1 });
      const stillAvailable = await deps.checkFresh();
      if (!stillAvailable) return { kind: "sold-out" };
      deps.onPhase({ kind: "retrying", attempt: attempt + 1 });
    }
  }
}
