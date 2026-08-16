// 검색 폼 검증 — F03 계약의 400 조건을 폼에서 미리 알려준다.
// 클라이언트 검증은 UX이지 보안이 아니다. 서버가 400을 주면 그 답이 우선한다.

export interface SearchFormValues {
  checkIn: string;
  checkOut: string;
  guestCount: number;
  roomCount: number;
}

import { nightsBetween } from "./dates";

export type SearchFormErrors = Partial<Record<keyof SearchFormValues, string>>;

// 30박 상한은 **백엔드가 실제로 400을 주기 때문에** 남아 있다.
// 2026-08-17 실측: GET /api/availability에 40박을 넣으면
//   400 INVALID_REQUEST "투숙은 30박을 넘을 수 없습니다"
// (origin/main의 app/inventory/query/application/commands.py:17 MAX_NIGHTS = 30)
//
// 관리자 지시 D29("n박 제한 없이")로 F03이 이 상한을 걷어낸다고 알려왔으나(2026-08-17),
// 그 변경은 아직 main에 없다. **백엔드가 걷히기 전에 여기만 지우면** 폼의 명확한 안내가
// 서버 400 오류 화면으로 바뀌어 오히려 나빠진다 — 그래서 지금은 유지한다.
//
// 걷어낼 조건: 백엔드 상한이 main에 병합되어 긴 기간이 200 + emptyReason: NOT_YET_OPEN
// (+ salesOpenUntil)으로 응답하는 것을 실측으로 확인한 뒤. 그때는 이 상수와 25~26행,
// 그리고 search-form.test.ts의 30박 케이스를 함께 지운다. 판매 기간 밖 안내 화면은
// 이미 구현돼 있어 추가 화면 작업은 없다.
const MAX_NIGHTS = 30;

export function validateSearchForm(v: SearchFormValues, today: string): SearchFormErrors {
  const errors: SearchFormErrors = {};

  if (!v.checkIn) errors.checkIn = "체크인 날짜를 선택해 주세요.";
  else if (v.checkIn < today) errors.checkIn = "체크인은 오늘부터 선택할 수 있습니다.";

  if (!v.checkOut) errors.checkOut = "체크아웃 날짜를 선택해 주세요.";
  else if (v.checkOut <= v.checkIn) errors.checkOut = "체크아웃은 체크인보다 뒤여야 합니다.";
  else if (nightsBetween(v.checkIn, v.checkOut) > MAX_NIGHTS)
    errors.checkOut = `한 번에 최대 ${MAX_NIGHTS}박까지 검색할 수 있습니다.`;

  if (!Number.isInteger(v.guestCount) || v.guestCount < 1 || v.guestCount > 20)
    errors.guestCount = "인원은 1~20명 사이여야 합니다.";

  if (!Number.isInteger(v.roomCount) || v.roomCount < 1 || v.roomCount > 10)
    errors.roomCount = "객실 수는 1~10개 사이여야 합니다.";

  return errors;
}
