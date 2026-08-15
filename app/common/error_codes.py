"""API 에러 코드 계약.

**이 집합이 클라이언트와의 계약이다.** 응답 본문의 `code`에 실릴 수 있는 문자열은
여기 있는 것뿐이고, 여기 없는 문자열이 나가면 계약 위반이다.

**왜 별도 모듈인가.** 계약을 사람이 읽는 문서(스펙)에만 두면 코드와 어긋나도
아무도 모른다. 어긋나는 방식이 특히 나쁘다 — **HTTP 상태 코드는 정상으로 나가고
`code` 문자열만 다르다.** 눈으로 보면 멀쩡하고, 부하테스트가 `code`를 비교하는
시점에야 드러난다. 그래서 계약을 기계가 읽을 수 있는 자리에 한 번 더 둔다.

`tests/test_error_contract.py`가 이 집합과 코드베이스의 예외 클래스를 대조한다.

**스펙 표와 이 집합은 같은 커밋에서 함께 바뀐다.** 사람이 읽는 정의는
`docs/spec/F01-예약-코어.md` 2.1절의 「에러 코드 계약」 표에 있다.
"""

from types import MappingProxyType

# 코드 → HTTP 상태. 상태 코드는 "받는 쪽이 무엇을 해야 하는가"로 고른다.
ERROR_CODE_STATUS: MappingProxyType[str, int] = MappingProxyType(
    {
        # 400 — 요청이 틀렸다. 고쳐서 다시 보내야 한다
        "INVALID_REQUEST": 400,
        # 404 — 대상이 없다. 남의 예약도 이것이다(403이면 존재를 알려주게 된다)
        "RESOURCE_NOT_FOUND": 404,
        # 409 — 요청은 맞지만 지금 상태에서 안 된다
        "INVALID_STATE_TRANSITION": 409,
        "INSUFFICIENT_INVENTORY": 409,
        "REQUEST_IN_PROGRESS": 409,
        # 503 — 혼잡했을 뿐이다. 잠시 뒤 그대로 다시 보내면 된다
        "LOCK_ACQUISITION_FAILED": 503,
        # 500 — 예상 못 한 실패. 도메인 예외가 아니라 최상위 핸들러에서만 난다
        "INTERNAL_ERROR": 500,
    }
)

API_ERROR_CODES: frozenset[str] = frozenset(ERROR_CODE_STATUS)
