// 상태 → 표기·행동 매핑. 진실은 시안 S3의 「상태 → 행동 매핑」 표다.
//
// 서버 응답에 "가능한 행동 목록"이 없으므로 화면이 이 표 하나를 갖는다 — 여기 한 곳에만.
// 이 표가 서버의 전이 표와 어긋나면 서버가 409로 거부하고, 화면은 재조회로 서버의
// 진실을 따른다. CANCELLED은 failureReason 유무로 "취소됨"과 "결제 거절"을 나눈다 —
// 시스템에는 같은 상태지만 사용자에게는 전혀 다른 사건이다.

import type { ReservationStatus } from "./contracts";

export type ReservationAction = "confirm" | "cancel" | "rebook";

export interface ReservationView {
  badgeLabel: string;
  tone: "ok" | "warn" | "danger" | "info" | "mute";
  title: string;
  description: string;
  actions: ReservationAction[];
  showCountdown: boolean;
  /** rebook 행동의 버튼 라벨 — 사용자 취소만 "다른 날짜 검색" (시안 S3 상태 4) */
  rebookLabel?: string;
}

interface ViewInput {
  status: ReservationStatus;
  failureReason?: string;
}

export function viewOf(r: ViewInput): ReservationView {
  switch (r.status) {
    case "PENDING":
      return {
        badgeLabel: "결제 대기",
        tone: "warn",
        title: "방을 잡아 두었습니다",
        description: "시간 안에 결제하지 않으면 자동으로 취소되고 방은 다시 판매됩니다.",
        actions: ["confirm", "cancel"],
        showCountdown: true,
      };
    case "CONFIRMED":
      return {
        badgeLabel: "예약 확정",
        tone: "ok",
        title: "예약이 확정되었습니다",
        description: "확인번호를 체크인 때 알려주세요.",
        actions: ["cancel"],
        showCountdown: false,
      };
    case "CANCELLED":
      if (r.failureReason) {
        return {
          badgeLabel: "결제 거절",
          tone: "danger",
          title: "결제가 거절되어 예약이 취소되었습니다",
          description:
            "잡아 두었던 방은 다시 판매됩니다. 결제 수단을 확인한 뒤 처음부터 다시 예약해 주세요.",
          actions: ["rebook"],
          showCountdown: false,
          rebookLabel: "같은 조건으로 다시 예약",
        };
      }
      return {
        badgeLabel: "취소됨",
        tone: "mute",
        title: "예약이 취소되었습니다",
        description: "방은 다시 판매됩니다.",
        actions: ["rebook"],
        showCountdown: false,
        rebookLabel: "다른 날짜 검색",
      };
    case "EXPIRED":
      return {
        badgeLabel: "시간 초과",
        tone: "warn",
        title: "결제 시간이 지나 예약이 취소되었습니다",
        description:
          "10분 안에 결제가 완료되지 않아 방이 다시 판매되었습니다. 같은 조건으로 다시 예약할 수 있습니다.",
        actions: ["rebook"],
        showCountdown: false,
        rebookLabel: "같은 조건으로 다시 예약",
      };
    case "CHECKED_IN":
      return {
        badgeLabel: "투숙 중",
        tone: "info",
        title: "투숙 중입니다",
        description: "체크아웃은 프런트에서 처리됩니다.",
        actions: [], // 체크인·체크아웃 버튼은 두지 않는다 — 직원 액션 (시안 D8)
        showCountdown: false,
      };
    case "CHECKED_OUT":
      return {
        badgeLabel: "숙박 완료",
        tone: "mute",
        title: "숙박이 끝난 예약입니다",
        description: "이 예약의 상태는 더 바뀌지 않습니다.",
        actions: [],
        showCountdown: false,
      };
  }
}
