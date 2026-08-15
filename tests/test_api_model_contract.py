"""응답 모델 표기 계약 — 모든 `~Response`는 `ApiModel`을 상속한다.

**막으려는 실패 모드 (F04 발견).** `ApiModel` 상속을 빠뜨린 스키마는 그
엔드포인트만 조용히 `snake_case`로 나간다. HTTP는 정상이고 본문 구조도
그럴듯해서 눈으로는 못 잡는데, k6는 **표본이 0건인 지표의 임계값을 조용히
통과시킨다** — 필드명이 어긋나면 "0%였다"가 아니라 "검사하지 않았다"인데
화면에는 초록이 나온다. 에러 코드 계약 테스트와 같은 부류의 방어다.
"""

import importlib
import inspect
import pkgutil

from pydantic import BaseModel

import app
from app.common.response import ApiModel


def _all_response_models() -> list[type[BaseModel]]:
    """`app` 아래에서 이름이 `Response`로 끝나는 Pydantic 모델을 전부 모은다."""
    found: dict[str, type[BaseModel]] = {}
    for module_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        module = importlib.import_module(module_info.name)
        for _, member in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(member, BaseModel)
                and member.__name__.endswith("Response")
                and member.__module__.startswith("app.")
            ):
                found[f"{member.__module__}.{member.__qualname__}"] = member
    return list(found.values())


def test_모든_Response_모델은_ApiModel을_상속한다():
    models = _all_response_models()

    # 모집단 확인. 0개면 통과가 아니라 검사를 안 한 것이다 —
    # 스캐폴딩의 ErrorResponse가 있으므로 최소 1개는 나와야 한다.
    assert models, "Response 모델을 하나도 못 찾았다. 순회가 깨졌다"

    위반 = [
        f"{m.__module__}.{m.__qualname__}"
        for m in models
        if not issubclass(m, ApiModel)
    ]
    assert not 위반, (
        f"ApiModel을 상속하지 않은 응답 모델이다: {위반} — "
        "이 엔드포인트만 조용히 snake_case로 나간다"
    )
