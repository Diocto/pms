"""API 경계의 공통 응답 형태.

**파이썬 식별자는 `snake_case`, API JSON은 `camelCase`다.** 그리고 그 변환은
`presentation` 계층 한 곳에서만 일어난다. 두 곳에서 변환하면 어느 경로로
들어왔는지에 따라 응답 모양이 달라진다.

모든 요청·응답 스키마는 `ApiModel`을 상속한다. 상속하지 않으면 그 엔드포인트만
`snake_case`로 나가고, 그건 클라이언트가 깨질 때까지 아무도 모른다.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """웹 경계 스키마의 기반. 직렬화 시 `camelCase`로 나간다.

    `populate_by_name=True`라서 파이썬 코드에서는 원래 필드 이름으로 만들 수 있다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ErrorResponse(ApiModel):
    """모든 실패 응답의 형태. 스택 트레이스는 절대 싣지 않는다."""

    code: str
    message: str
    trace_id: str
