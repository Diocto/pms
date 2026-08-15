"""공통 예외 계층.

**도메인 코드에 HTTP 상태 코드가 등장하면 안 된다.** 그런데 예외를 HTTP로 바꾸는
곳에서는 무엇을 몇 번으로 내보낼지 알아야 한다. 이 둘을 동시에 만족시키려고
중간 단계를 하나 둔다.

    DomainError                 ← 도메인 언어로 표현된 실패
    ├── InvalidRequestError        요청 자체가 틀렸다.        재시도해도 소용없다
    ├── NotFoundError              대상이 없다
    ├── ConflictError              요청은 맞지만 지금 상태에서 안 된다
    └── ServiceUnavailableError    지금은 처리할 수 없다.     잠시 뒤 재시도하면 된다

**갈래는 "무엇이 일어났는가"가 아니라 "받는 쪽이 무엇을 해야 하는가"로 나눈 것이다.**
그래서 HTTP 상태 코드와 일대일로 대응하면서도 HTTP를 모른다.

각 컨텍스트는 이 중 하나를 상속해 자기 예외를 만들고 `code`만 바꾼다.

    class InsufficientInventoryError(ConflictError):
        code = "INSUFFICIENT_INVENTORY"

`code`가 클라이언트와의 계약이다. 메시지는 사람이 읽는 것이라 바뀔 수 있지만
`code`는 바뀌면 계약 위반이다.

**계약에 없는 기본값을 두지 않는다.**
`code`의 기본값이 계약 밖 문자열이면 그 값이 나가는 순간 무조건 계약 위반인데,
**HTTP 상태 코드는 정상이라 눈으로는 멀쩡해 보인다.** 실패는 부하테스트가
`code` 문자열을 비교하는 시점에야 드러난다. 그래서 규칙을 둘로 나눴다.

- 일반적인 코드가 계약에 있는 갈래(400·404)는 그 코드를 기본값으로 갖는다
- 항상 구체적 이유가 붙는 갈래(409·503)는 **기본값을 두지 않고, 그대로 만들면 즉시 터진다**

계약에 정의된 코드 전체는 `docs/spec/F01-예약-코어.md` 2.1절의 표에 있고,
`tests/test_error_contract.py`가 그 표와 이 코드를 대조한다.
"""


class DomainError(Exception):
    """도메인 규칙이 거부한 것. 프로그래밍 오류(`TypeError` 등)와 구분한다.

    `code`가 없는 채로 만들면 `TypeError`다. 중간 갈래를 그대로 던지는 실수를
    조용히 넘기지 않기 위해서다.
    """

    code: str | None = None

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if self.code is None:
            raise TypeError(
                f"{type(self).__name__}에는 `code`가 없다. "
                "하위 클래스에서 정하거나 code= 인자로 넘겨라. "
                "계약에 없는 코드가 응답으로 나가는 것을 막기 위한 것이다."
            )


class InvalidRequestError(DomainError):
    """요청이 규칙에 어긋난다. 같은 요청을 다시 보내도 같은 결과다. → 400"""

    code = "INVALID_REQUEST"


class NotFoundError(DomainError):
    """가리키는 대상이 없다. → 404

    남의 예약을 조회했을 때도 이것이다. 403을 주면 그 확인번호가 존재한다는
    사실 자체를 알려주게 된다.
    """

    code = "RESOURCE_NOT_FOUND"


class ConflictError(DomainError):
    """요청 자체는 유효하지만 현재 상태에서는 받아들일 수 없다. → 409

    재고 부족, 허용되지 않는 상태 전이, 처리 중인 멱등 키가 여기 온다.
    조건이 바뀌면 같은 요청이 성공할 수 있다는 점이 `InvalidRequestError`와 다르다.

    **기본 `code`가 없다.** 409는 언제나 구체적인 이유가 있어서 이 클래스를
    그대로 던질 일이 없고, 계약에도 포괄적인 409 코드가 없다.
    """


class ServiceUnavailableError(DomainError):
    """지금은 처리할 수 없다. 잠시 뒤 같은 요청을 다시 보내면 된다. → 503

    분산락 획득 실패가 여기 온다. 요청에도 상태에도 잘못이 없고 **혼잡했을 뿐**이라
    4xx로 답하면 클라이언트가 요청을 고치려 든다.

    **기본 `code`가 없다.** 이유는 `ConflictError`와 같다.
    """
