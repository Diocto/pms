"""`RuntimeContributor` 계약 (D26) — 기여 그릇과 병합 규칙.

각 컨텍스트가 자기 설정·구현체·카운터를 `RuntimeReport`로 내놓고,
F01의 `/api/internal/config` 라우트가 리스트로 모아 병합한다.

병합에서 지켜야 하는 것 하나: **키 충돌은 조용히 덮어쓰지 않는다.**
컨텍스트별 접두가 갈리므로 정상 경로에서 충돌이 없고,
있다면 같은 키를 두 곳이 소유한다는 뜻이라 실패시킨다.
"""

import pytest
from pydantic import ValidationError

from app.common.runtime_report import RuntimeReport, merge_reports


def test_보고서는_얼어_있다():
    """실행 설정 보고(D26) — RuntimeReport는 frozen이라 만들어진 뒤 필드에
    대입하면 ValidationError다. 병합 과정에서 기여자의 보고가 변형되는 것을
    막는다."""
    report = RuntimeReport(load_test={"PMS_LOCK_ENABLED": True})
    with pytest.raises(ValidationError):
        report.load_test = {}


def test_병합은_컨텍스트별_보고를_한_응답으로_합친다():
    """실행 설정 보고(D26) — 여러 컨텍스트의 보고가 load_test·implementations·
    counters 세 칸별로 합쳐져 한 응답이 된다."""
    f01 = RuntimeReport(
        load_test={"PMS_LOCK_ENABLED": False, "PMS_LOCK_TTL_SECONDS": 3},
        implementations={"LockPort": "NoOpLockAdapter"},
    )
    f02 = RuntimeReport(
        load_test={"PMS_PROMOTION_OPEN_AT": "2026-09-01T10:00:00"},
        counters={"rejected_by_gate": 0},
    )
    merged = merge_reports([f01, f02])
    assert merged.load_test == {
        "PMS_LOCK_ENABLED": False,
        "PMS_LOCK_TTL_SECONDS": 3,
        "PMS_PROMOTION_OPEN_AT": "2026-09-01T10:00:00",
    }
    assert merged.implementations == {"LockPort": "NoOpLockAdapter"}
    assert merged.counters == {"rejected_by_gate": 0}


def test_기여자가_없으면_빈_응답이다():
    """실행 설정 보고(D26) — 기여자가 하나도 없으면 세 칸 모두 빈 dict다.
    다른 feature가 아직 없어도 F01 코어가 그대로 돈다는 확인이다."""
    merged = merge_reports([])
    assert merged.load_test == {}
    assert merged.implementations == {}
    assert merged.counters == {}


def test_설정_키가_충돌하면_조용히_덮어쓰지_않고_실패한다():
    """실행 설정 보고(D26) — 같은 load_test 키를 두 보고가 내면 나중 값으로
    덮지 않고 키 이름을 담은 ValueError로 실패한다. 덮어쓰면 어느 쪽 값이
    보고됐는지 아무도 모른 채 실험이 그 값을 믿게 된다."""
    first = RuntimeReport(load_test={"PMS_LOCK_ENABLED": True})
    second = RuntimeReport(load_test={"PMS_LOCK_ENABLED": False})
    with pytest.raises(ValueError, match="PMS_LOCK_ENABLED"):
        merge_reports([first, second])


def test_구현체_키가_충돌해도_같다():
    """실행 설정 보고(D26) — implementations 키 충돌도 같은 규칙으로
    ValueError다."""
    first = RuntimeReport(implementations={"LockPort": "RedisLockAdapter"})
    second = RuntimeReport(implementations={"LockPort": "NoOpLockAdapter"})
    with pytest.raises(ValueError, match="LockPort"):
        merge_reports([first, second])


def test_카운터_키가_충돌해도_같다():
    """실행 설정 보고(D26) — counters 키 충돌도 같은 규칙으로 ValueError다."""
    first = RuntimeReport(counters={"rejected_by_gate": 3})
    second = RuntimeReport(counters={"rejected_by_gate": 5})
    with pytest.raises(ValueError, match="rejected_by_gate"):
        merge_reports([first, second])
