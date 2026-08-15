"""에러 코드 계약과 코드베이스를 대조한다.

**이 테스트가 막으려는 실패 모드.** 예외 클래스의 `code`가 계약에 없는 문자열이면
**HTTP 상태 코드는 정상으로 나가고 `code`만 다르다.** 응답을 눈으로 보면 멀쩡해서
개발 중에는 아무도 못 잡고, 부하테스트가 `code`를 비교하는 시점에야 드러난다.
Enum을 값으로 저장해 검증 SQL이 0행을 돌려주는 것과 정확히 같은 종류다.

실제로 이 방식으로 한 번 어긋났다 — `NotFoundError`의 기본값이 계약에 없는
`NOT_FOUND`였고, F03이 응답 본문을 직접 보고 나서야 발견했다.
"""

import importlib
import inspect
import pkgutil

import pytest

import app
from app.common.error_codes import API_ERROR_CODES, ERROR_CODE_STATUS
from app.common.error_handlers import _STATUS_BY_TYPE, INTERNAL_ERROR_CODE
from app.common.errors import DomainError


def _all_domain_error_classes() -> list[type[DomainError]]:
    """`app` 아래 모든 모듈을 훑어 `DomainError` 하위 클래스를 모은다.

    컨텍스트가 늘어날 때마다 이 목록에 손대지 않아도 되게 순회로 찾는다.
    등록을 빠뜨려서 검사에서 새는 일을 없애기 위한 것이다.
    """
    found: dict[str, type[DomainError]] = {}
    for module_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        module = importlib.import_module(module_info.name)
        for _, member in inspect.getmembers(module, inspect.isclass):
            if issubclass(member, DomainError) and member is not DomainError:
                found[f"{member.__module__}.{member.__qualname__}"] = member
    return list(found.values())


def test_예외_클래스의_코드는_전부_계약_안에_있다():
    classes = _all_domain_error_classes()

    # 모집단을 먼저 확인한다. 한 개도 못 찾았으면 통과가 아니라 검사를 안 한 것이다.
    assert classes, "DomainError 하위 클래스를 하나도 못 찾았다. 순회가 깨졌다"

    위반 = {
        f"{cls.__module__}.{cls.__qualname__}": cls.code
        for cls in classes
        if cls.code is not None and cls.code not in API_ERROR_CODES
    }
    assert not 위반, f"계약에 없는 코드다: {위반}"


def test_기본_코드가_있는_갈래는_그_코드가_계약_안에_있다():
    """기본값은 특히 위험하다. 하위 클래스가 안 덮으면 그대로 나가기 때문이다."""
    from app.common.errors import InvalidRequestError, NotFoundError

    assert InvalidRequestError.code in API_ERROR_CODES
    assert NotFoundError.code in API_ERROR_CODES
    # 이 테스트가 잡았어야 했던 그 값
    assert NotFoundError.code == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    "cls_name",
    ["ConflictError", "ServiceUnavailableError"],
)
def test_구체적_이유가_필요한_갈래는_그대로_던질_수_없다(cls_name: str):
    """계약에 포괄적인 409·503 코드가 없다.

    한 번도 유효할 수 없는 기본값을 두느니 만드는 순간 터지게 한다.
    """
    import app.common.errors as errors_module

    cls = getattr(errors_module, cls_name)
    with pytest.raises(TypeError):
        cls("이유 없이 만들면 안 된다")


def test_갈래마다_상태_코드가_계약과_같다():
    """예외 갈래 → HTTP 상태 표가 계약 표와 어긋나지 않는지 본다."""
    갈래_상태 = {status for _, status in _STATUS_BY_TYPE}
    계약_상태 = {
        status for code, status in ERROR_CODE_STATUS.items() if code != INTERNAL_ERROR_CODE
    }
    assert 갈래_상태 == 계약_상태, (
        f"갈래가 내보내는 상태 {sorted(갈래_상태)}와 "
        f"계약의 상태 {sorted(계약_상태)}가 다르다. "
        "계약에 있는 상태를 낼 수 있는 갈래가 없으면 그 코드는 절대 안 나간다"
    )


def test_예상_못_한_예외의_코드도_계약_안에_있다():
    assert INTERNAL_ERROR_CODE in API_ERROR_CODES
