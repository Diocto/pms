"""응답 모델 표기 계약 — 모든 `~Response`는 `ApiModel`을 상속한다.

**막으려는 실패 모드 (부하테스트 발견).** `ApiModel` 상속을 빠뜨린 스키마는 그
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


def test_모든_파이썬_디렉터리에_init이_있다():
    """`__init__.py`가 없는 패키지는 `walk_packages` 순회에서 조용히 빠진다.

    그 패키지에 예외·응답 모델이 들어오는 순간 계약 검사가 그것을 못 보는데
    테스트는 초록이다 — 이 파일과 error 계약 테스트의 존재 목적이 무력화된다
    (리뷰 지적). 구조적으로 재발을 막는다.
    """
    import pathlib

    app_root = pathlib.Path(app.__path__[0])
    missing = [
        str(directory.relative_to(app_root.parent))
        for directory in app_root.rglob("*")
        if directory.is_dir()
        and directory.name != "__pycache__"
        and any(directory.glob("*.py"))
        and not (directory / "__init__.py").exists()
    ]
    assert missing == [], f"__init__.py가 없어 순회에서 빠지는 패키지: {missing}"


def test_모든_Response_모델은_ApiModel을_상속한다():
    """API 응답 모양(camelCase) — 이름이 Response로 끝나는 모든 Pydantic 모델이
    ApiModel을 상속한다. 상속을 빠뜨린 스키마는 그 엔드포인트만 조용히
    snake_case로 나가고, k6는 어긋난 필드명을 "표본 0건 통과"로 삼킨다."""
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
