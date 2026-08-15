"""`ConfigContributor` 계약 (D26) — 기여 그릇과 병합 규칙.

각 컨텍스트가 자기 설정·구현체 정보를 `ConfigReport`로 내놓고,
F01의 `/api/internal/config` 라우트가 리스트로 모아 병합한다.

병합에서 지켜야 하는 것 하나: **키 충돌은 조용히 덮어쓰지 않는다.**
`PMS_` 접두가 컨텍스트별로 갈리므로 정상 경로에서 충돌이 없고,
있다면 같은 키를 두 곳이 소유한다는 뜻이라 실패시킨다.
"""

import pytest
from pydantic import ValidationError

from app.common.config_report import ConfigReport, merge_reports


def _report(**kwargs) -> ConfigReport:
    base = {"load_test": {}, "implementations": {}}
    base.update(kwargs)
    return ConfigReport(**base)


def test_보고서는_얼어_있다():
    report = _report(load_test={"PMS_LOCK_ENABLED": True})
    with pytest.raises(ValidationError):
        report.load_test = {}


def test_병합은_컨텍스트별_보고를_한_응답으로_합친다():
    f01 = _report(
        load_test={"PMS_LOCK_ENABLED": False, "PMS_LOCK_TTL_SECONDS": 3},
        implementations={"LockPort": "NoOpLockAdapter"},
    )
    f02 = _report(
        load_test={"PMS_PROMOTION_OPEN_AT": "2026-09-01T10:00:00"},
        implementations={"PromotionClockPort": "SystemClock"},
    )
    merged = merge_reports([f01, f02])
    assert merged.load_test == {
        "PMS_LOCK_ENABLED": False,
        "PMS_LOCK_TTL_SECONDS": 3,
        "PMS_PROMOTION_OPEN_AT": "2026-09-01T10:00:00",
    }
    assert merged.implementations == {
        "LockPort": "NoOpLockAdapter",
        "PromotionClockPort": "SystemClock",
    }


def test_기여자가_없으면_빈_응답이다():
    merged = merge_reports([])
    assert merged.load_test == {}
    assert merged.implementations == {}


def test_설정_키가_충돌하면_조용히_덮어쓰지_않고_실패한다():
    first = _report(load_test={"PMS_LOCK_ENABLED": True})
    second = _report(load_test={"PMS_LOCK_ENABLED": False})
    with pytest.raises(ValueError, match="PMS_LOCK_ENABLED"):
        merge_reports([first, second])


def test_구현체_키가_충돌해도_같다():
    first = _report(implementations={"LockPort": "RedisLockAdapter"})
    second = _report(implementations={"LockPort": "NoOpLockAdapter"})
    with pytest.raises(ValueError, match="LockPort"):
        merge_reports([first, second])
