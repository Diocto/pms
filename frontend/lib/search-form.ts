// 검색 폼 검증 — 검색 계약의 400 조건을 폼에서 미리 알려준다.
// 클라이언트 검증은 UX이지 보안이 아니다. 서버가 400을 주면 그 답이 우선한다.

export interface SearchFormValues {
  checkIn: string;
  checkOut: string;
  guestCount: number;
  roomCount: number;
}

export type SearchFormErrors = Partial<Record<keyof SearchFormValues, string>>;

// 박수 상한은 두지 않는다 (관리자 지시 D29 "n박 제한 없이", 2026-08-16).
// 서버도 상한이 없다 — 예약 PR #63, 검색 PR #65에서 걷혔다.
//
// 긴 기간을 클라이언트가 미리 막지 않는 이유: 판매 기간을 넘는 요청에 서버가 400이 아니라
// 200 + emptyReason: NOT_YET_OPEN + salesOpenUntil로 답하고, 화면은 그걸 "아직 판매를
// 열지 않은 날짜입니다 / ~까지 판매 중입니다"로 그린다. 오타로 연도를 잘못 넣은 경우
// (2026-08-17 실측: 405박 → NOT_YET_OPEN + salesOpenUntil 2026-10-29)에도 그 안내가
// "최대 N박까지"라는 임의 숫자보다 손님에게 쓸모 있다.

export function validateSearchForm(v: SearchFormValues, today: string): SearchFormErrors {
  const errors: SearchFormErrors = {};

  if (!v.checkIn) errors.checkIn = "체크인 날짜를 선택해 주세요.";
  else if (v.checkIn < today) errors.checkIn = "체크인은 오늘부터 선택할 수 있습니다.";

  if (!v.checkOut) errors.checkOut = "체크아웃 날짜를 선택해 주세요.";
  else if (v.checkOut <= v.checkIn) errors.checkOut = "체크아웃은 체크인보다 뒤여야 합니다.";

  if (!Number.isInteger(v.guestCount) || v.guestCount < 1 || v.guestCount > 20)
    errors.guestCount = "인원은 1~20명 사이여야 합니다.";

  if (!Number.isInteger(v.roomCount) || v.roomCount < 1 || v.roomCount > 10)
    errors.roomCount = "객실 수는 1~10개 사이여야 합니다.";

  return errors;
}
