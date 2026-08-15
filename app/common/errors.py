"""공통 예외 계층.

**도메인 코드에 HTTP 상태 코드가 등장하면 안 된다.** 그런데 예외를 HTTP로 바꾸는
곳에서는 무엇을 몇 번으로 내보낼지 알아야 한다. 이 둘을 동시에 만족시키려고
중간 단계를 하나 둔다.

    DomainError            ← 도메인 언어로 표현된 실패
    ├── InvalidRequestError   요청 자체가 틀렸다.        재시도해도 소용없다
    ├── NotFoundError         대상이 없다
    └── ConflictError         요청은 맞지만 지금은 안 된다. 재시도할 수 있다

**세 갈래는 "무엇이 일어났는가"가 아니라 "받는 쪽이 무엇을 해야 하는가"로 나눈 것이다.**
그래서 HTTP 상태 코드와 일대일로 대응하면서도 HTTP를 모른다.

각 컨텍스트는 이 셋 중 하나를 상속해 자기 예외를 만들고 `code`만 바꾼다.

    class InsufficientInventoryError(ConflictError):
        code = "INSUFFICIENT_INVENTORY"

`code`가 클라이언트와의 계약이다. 메시지는 사람이 읽는 것이라 바뀔 수 있지만
`code`는 바뀌면 계약 위반이다.
"""


class DomainError(Exception):
    """도메인 규칙이 거부한 것. 프로그래밍 오류(`TypeError` 등)와 구분한다."""

    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class InvalidRequestError(DomainError):
    """요청이 규칙에 어긋난다. 같은 요청을 다시 보내도 같은 결과다."""

    code = "INVALID_REQUEST"


class NotFoundError(DomainError):
    """가리키는 대상이 없다."""

    code = "NOT_FOUND"


class ConflictError(DomainError):
    """요청 자체는 유효하지만 현재 상태에서는 받아들일 수 없다.

    재고 부족, 허용되지 않는 상태 전이, 처리 중인 멱등 키가 여기 온다.
    조건이 바뀌면 같은 요청이 성공할 수 있다는 점이 `InvalidRequestError`와 다르다.
    """

    code = "CONFLICT"
