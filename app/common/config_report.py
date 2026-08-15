"""설정 노출 기여 계약 (D26).

`GET /api/internal/config`는 F01이 라우트를 소유하지만, 싣는 내용은 컨텍스트마다
자기 것이 있다 — F01의 락·결제, F02의 프로모션, F03의 캐시. 엔드포인트를
컨텍스트마다 따로 파면 "설정을 두 곳에서 따로 읽는" 상태가 되고, F01이 다른
컨텍스트의 컨테이너를 직접 읽으면 의존 방향이 뒤집힌다.

그래서 계약을 여기(`common` — 아무에게도 의존하지 않는다)에 두고, 각 컨텍스트가
자기 컨테이너에 `ConfigContributor` 구현 하나를 등록하며, F01의 라우트가 리스트
프로바이더로 모아 `merge_reports`로 합친다. 구현이 0개인 컨텍스트는 자연히
응답에 나오지 않는다.

두 규칙이 그릇에 박혀 있다.

- `load_test`의 키는 **조작자가 셸에 치는 환경변수 이름 그대로**다. 이 응답은
  사람이 읽고 셸에 옮겨 적는 유일한 응답이라, 표기 규칙(camelCase)보다
  "친 것과 같아야 한다"가 우선한다
- `implementations`의 값은 **컨테이너에서 실제로 꺼낸 객체의 클래스 이름**이다
  (`type(container.lock()).__name__`). 손으로 적은 문자열은 배선과 어긋날
  자리가 된다 — 설정 값은 "무엇을 의도했는가"이고 이 값은 "실제로 무엇이
  들어갔는가"다
"""

from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ConfigReport(BaseModel):
    """한 컨텍스트가 내놓는 설정·구현체 정보. 계층을 넘는 그릇이므로 Pydantic이다."""

    model_config = ConfigDict(frozen=True)

    load_test: dict[str, bool | int | float | str]
    implementations: dict[str, str]


class ConfigContributor(Protocol):
    def report(self) -> ConfigReport: ...


def merge_reports(reports: Iterable[ConfigReport]) -> ConfigReport:
    """컨텍스트별 보고를 한 응답으로 합친다.

    **키가 충돌하면 조용히 덮어쓰지 않고 실패한다.** `PMS_` 접두가 컨텍스트별로
    갈리므로 정상 경로에서 충돌이 없고, 있다면 같은 키를 두 곳이 소유한다는
    뜻이다 — 어느 쪽 값이 이기든 한쪽의 보고는 거짓이 된다.
    """
    load_test: dict[str, bool | int | float | str] = {}
    implementations: dict[str, str] = {}
    for report in reports:
        for key in report.load_test:
            if key in load_test:
                raise ValueError(f"설정 키를 두 컨텍스트가 실었다: {key}")
        for key in report.implementations:
            if key in implementations:
                raise ValueError(f"구현체 키를 두 컨텍스트가 실었다: {key}")
        load_test.update(report.load_test)
        implementations.update(report.implementations)
    return ConfigReport(load_test=load_test, implementations=implementations)
