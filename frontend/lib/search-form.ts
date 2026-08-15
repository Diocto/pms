// 검색 폼 검증 — F03 계약의 400 조건을 폼에서 미리 알려준다.
// 클라이언트 검증은 UX이지 보안이 아니다. 서버가 400을 주면 그 답이 우선한다.

export interface SearchFormValues {
  checkIn: string;
  checkOut: string;
  guestCount: number;
  roomCount: number;
}

export type SearchFormErrors = Partial<Record<keyof SearchFormValues, string>>;

const MAX_NIGHTS = 30;

function nightsBetween(checkIn: string, checkOut: string): number {
  return Math.round((Date.parse(checkOut) - Date.parse(checkIn)) / 86_400_000);
}

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
